/*
 * tcm-link: USB link helper for Texas CAS Manager.
 *
 * Runs as a child process of the GUI and talks to a TI-Nspire over USB using
 * libticalcs2 (TiLP). The GUI writes one request per line on stdin and reads
 * one JSON object per line on stdout. Running the USB code in a separate
 * process keeps the GUI alive if libusb or libticalcs crash or hang.
 *
 * Request:   <id>\t<command>[\t<arg>]...\n
 * Response:  {"id":<id>,"ok":true,...}  or  {"id":<id>,"ok":false,"code":N,"error":"..."}
 * Progress:  {"id":<id>,"event":"progress","done":N,"total":N}
 *
 * Commands (see docs/USB-PROTOCOL.md):
 *   hello                     helper version
 *   probe                     list TI USB product IDs, without opening a link
 *   open / close              open or close the link to the first TI-Nspire
 *   info                      device information (model, OS, storage, battery)
 *   list   <dir>              entries of one remote folder (not recursive)
 *   get    <remote> <local>   download a remote file into a local path
 *   put    <local> <remote>   upload a local file to a remote path
 *   del    <remote>           delete a remote file
 *   mkdir  <remote>           create a remote folder
 *   rmdir  <remote>           delete a remote folder
 *   rename <remote> <remote>  rename or move a remote file
 *   listen <seconds>          diagnostic: receive and answer packets the
 *                             calculator sends on its own, list them
 *   quit                      close the link and exit
 *
 * Only the operations of the file management service (0x4060) used by
 * libticalcs itself are called. Remote paths are absolute ("/MyLib/x.tns")
 * and keep their real extension, unlike ticalcs_calc_get_dirlist().
 *
 * Session handling (measured on CX CAS OS 4.5.5, see docs/USB-PROTOCOL.md):
 * each service (file management 0x4060, device information 0x4020) gets its
 * own channel with its own host port, opened on first use and kept until the
 * link closes, and the packets the calculator sends on its own are answered.
 * Disconnecting from a service and talking to another one, as libticalcs does
 * around ticalcs_calc_get_version(), leaves the file service acknowledging
 * requests without answering them for ~45 s.
 */

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <glib.h>
#include <tilp2/ticables.h>
#include <tilp2/ticalcs.h>
#include <tilp2/nsp_cmd.h>
#include <tilp2/nsp_vpkt.h>

#define TCM_LINK_VERSION "1"
#define MAX_ARGS 4
/* libticalcs/src/error.h is not installed: ERR_EOT marks the end of a listing. */
#define TCM_ERR_EOT 262
/* Timeout in tenths of second for each packet read. */
#define LINK_TIMEOUT 100
/* Local error codes, outside the libticalcs/libticables ranges. */
#define E_USAGE 9001
#define E_NOT_OPEN 9002
#define E_LOCAL_IO 9003
#define E_TOO_BIG 9004
#define E_PROTOCOL 9005 /* unexpected reply from the calculator */
#define E_NACK 9006 /* the calculator refused the packet (service not available) */
/* The request was acknowledged but no reply came before the timeout: the
 * link works, the calculator's file service is busy (see docs/USB-PROTOCOL.md). */
#define E_BUSY 9007
/* Calculator status byte N (reply "FF N") is reported as 1000 + N. */
#define E_CALC_STATUS 1000

static CableHandle *cable;
static CalcHandle *calc;
static CalcUpdate update;
static const char *current_id = "0";
static int progress_enabled; /* only get/put report progress */
/* One channel per calculator service, each with its own host port. */
struct chan {
	uint16_t me;  /* host port */
	uint16_t svc; /* calculator service port */
	int used;     /* something was sent: disconnect on close */
};
static struct chan fm_chan = {0x8010, NSP_SID_FILE_MGMT, 0};
static struct chan di_chan = {0x8011, NSP_SID_DEV_INFOS, 0};

/* ---------- JSON output ---------- */

static void json_append(GString *out, const char *s)
{
	g_string_append_c(out, '"');
	for (const unsigned char *p = (const unsigned char *)s; *p; p++) {
		switch (*p) {
		case '"': g_string_append(out, "\\\""); break;
		case '\\': g_string_append(out, "\\\\"); break;
		case '\n': g_string_append(out, "\\n"); break;
		case '\r': g_string_append(out, "\\r"); break;
		case '\t': g_string_append(out, "\\t"); break;
		default:
			if (*p < 0x20)
				g_string_append_printf(out, "\\u%04x", *p);
			else
				g_string_append_c(out, (char)*p); /* UTF-8 bytes pass through */
		}
	}
	g_string_append_c(out, '"');
}

static void json_str(const char *s)
{
	GString *out = g_string_new(NULL);
	json_append(out, s);
	fputs(out->str, stdout);
	g_string_free(out, TRUE);
}

static void reply_begin(void)
{
	printf("{\"id\":");
	json_str(current_id);
	printf(",\"ok\":true");
}

static void reply_end(void)
{
	puts("}");
	fflush(stdout);
}

static void reply_ok(void)
{
	reply_begin();
	reply_end();
}

/* Status bytes documented on Hackspire (USB Protocol, file management). */
static const char *calc_status_text(int status)
{
	switch (status) {
	case 0x09: return "the parent folder does not exist";
	case 0x0A: return "the file or folder does not exist";
	case 0x0F: return "invalid folder name";
	case 0x11: return "no more entries";
	case 0x14: return "invalid file name";
	case 0x15: return "documents must have the .tns extension";
	default: return "the calculator refused the operation";
	}
}

static int reply_error(int code, const char *fallback)
{
	char *msg = NULL;

	if (code == E_BUSY) {
		fallback = "the calculator acknowledged the request but did not answer (file service busy)";
	} else if (code >= E_CALC_STATUS && code < E_CALC_STATUS + 256) {
		fallback = calc_status_text(code - E_CALC_STATUS);
	} else if (code < E_USAGE) {
		if (ticalcs_error_get(code, &msg) && ticables_error_get(code, &msg))
			msg = NULL;
	}
	printf("{\"id\":");
	json_str(current_id);
	printf(",\"ok\":false,\"code\":%d,\"error\":", code);
	json_str(msg ? msg : (fallback ? fallback : "unknown error"));
	reply_end();
	if (msg)
		ticalcs_error_free(msg);
	return code;
}

/* Called by libticalcs while packets are sent or received. */
static void on_progress(void)
{
	static int last;
	if (!progress_enabled || update.max1 <= 0)
		return;
	int done = update.cnt1 > update.max1 ? update.max1 : update.cnt1;
	/* Print at most ~100 events per transfer. */
	if (done != update.max1 && done - last < update.max1 / 100)
		return;
	last = done;
	printf("{\"id\":");
	json_str(current_id);
	printf(",\"event\":\"progress\",\"done\":%d,\"total\":%d}\n", done, update.max1);
	fflush(stdout);
}

static void noop(void) {}

static void log_to_stderr(const gchar *domain, GLogLevelFlags level, const gchar *msg, gpointer data)
{
	(void)level; (void)data;
	gint64 us = g_get_real_time();
	fprintf(stderr, "%02d.%03d %s: %s\n", (int)(us / 1000000 % 60), (int)(us / 1000 % 1000),
	        domain ? domain : "glib", msg);
}

static void reset_progress(void)
{
	progress_enabled = 1;
	update.cnt1 = update.max1 = 0;
	update.cancel = 0;
}

/* ---------- link ---------- */

static void chan_close(struct chan *ch);

static void link_close(void)
{
	if (calc && cable) {
		chan_close(&fm_chan);
		chan_close(&di_chan);
	}
	if (calc) {
		if (cable)
			ticalcs_cable_detach(calc);
		ticalcs_handle_del(calc);
		calc = NULL;
	}
	if (cable) {
		ticables_handle_del(cable);
		cable = NULL;
	}
}

static int link_open(void)
{
	int ret;

	link_close();
	cable = ticables_handle_new(CABLE_USB, PORT_1);
	calc = ticalcs_handle_new(CALC_NSPIRE);
	if (!cable || !calc) {
		link_close();
		return reply_error(E_NOT_OPEN, "cannot create libticalcs handles");
	}
	ticables_options_set_timeout(cable, LINK_TIMEOUT);
	update.start = update.stop = update.refresh = update.label = noop;
	update.pbar = on_progress;
	ticalcs_update_set(calc, &update);

	fm_chan.used = di_chan.used = 0;
	ret = ticalcs_cable_attach(calc, cable);
	if (!ret)
		ret = ticalcs_calc_isready(calc);
	if (ret) {
		link_close();
		return reply_error(ret, "calculator not ready");
	}
	reply_ok();
	return 0;
}

/*
 * File management (service 0x4060) packet layer.
 *
 * libticalcs' nsp_recv_data()/nsp_recv_ack() take the next packet as the
 * answer, whatever it is. On CX CAS OS 4.5.5 the calculator sends packets of
 * its own during file operations: a 1-byte 0x02 packet from a fresh
 * calculator port to our 0x4060 port (after every download, and instead of
 * the reply when a file does not exist), followed by a disconnection from
 * port 0x40DE. libticalcs reads them as the reply ("Invalid packet") and
 * acknowledges them to the wrong port, after which the calculator keeps
 * resending them and stops answering file requests for about a minute.
 *
 * Here every received packet is classified: our ACK, data for our session,
 * or unsolicited. Unsolicited packets are answered as Hackspire's USB
 * Protocol page describes for the device's LOGIN request (NACK from 0x00D3
 * with payload 0x4050) and disconnections are acknowledged (ACK from 0x00FF,
 * payload = the port they were addressed to); then we keep waiting.
 * Packet formats are copied from libticalcs nsp_cmd.cc / nsp_vpkt.cc.
 */
#define FM_STATUS 0xFF

static int is_ack_port(uint16_t port)
{
	return port == NSP_PORT_PKT_ACK1 || port == NSP_PORT_PKT_ACK2 || port == NSP_PORT_PKT_NACK;
}

static void answer_packet(const NSPRawPacket *in)
{
	NSPRawPacket reply;
	uint16_t payload;

	memset(&reply, 0, sizeof(reply));
	reply.data_size = 2;
	reply.src_addr = NSP_SRC_ADDR;
	reply.dst_addr = NSP_DEV_ADDR;
	reply.dst_port = in->src_port;
	if (in->src_port == NSP_PORT_DISCONNECT) {
		reply.src_port = NSP_PORT_PKT_ACK2;
		payload = in->dst_port;
	} else {
		reply.src_port = NSP_PORT_PKT_NACK;
		payload = NSP_PORT_LOGIN;
	}
	reply.data[0] = (uint8_t)(payload >> 8);
	reply.data[1] = (uint8_t)(payload & 0xFF);
	fprintf(stderr, "tcm-link: unsolicited packet %04x->%04x (%u bytes, first %02x): %s\n",
	        in->src_port, in->dst_port, in->data_size, in->data[0],
	        reply.src_port == NSP_PORT_PKT_NACK ? "NACK" : "ACK");
	nsp_send(calc, &reply); /* nsp_send() takes seq from the packet just received */
}

/* Answer whatever the calculator sends on its own within ~1 s (after a transfer). */
static void answer_unsolicited(void)
{
	unsigned int old = ticables_options_set_timeout(cable, 10);

	for (int i = 0; i < 8; i++) {
		NSPRawPacket in;
		memset(&in, 0, sizeof(in));
		if (nsp_recv(calc, &in))
			break; /* nothing pending */
		if (is_ack_port(in.src_port))
			continue;
		answer_packet(&in);
		if (in.src_port == NSP_PORT_DISCONNECT)
			break;
	}
	ticables_options_set_timeout(cable, old);
}

/* Wait for the ACK of the packet we just sent from port ``me``, answering anything else. */
static int wait_ack(uint16_t me)
{
	for (;;) {
		NSPRawPacket in;
		int ret;

		memset(&in, 0, sizeof(in));
		if ((ret = nsp_recv(calc, &in)))
			return ret;
		if (is_ack_port(in.src_port) && in.dst_port == me)
			return in.src_port == NSP_PORT_PKT_NACK ? E_NACK : 0;
		if (!is_ack_port(in.src_port))
			answer_packet(&in);
	}
}

/* Send one command (fragmented like nsp_send_data) and wait for each ACK. */
static int chan_send(struct chan *ch, uint8_t cmd, const uint8_t *data, uint32_t size)
{
	uint32_t offset = 0;

	do {
		NSPRawPacket raw;
		uint32_t chunk = size - offset < NSP_DATA_SIZE - 1 ? size - offset : NSP_DATA_SIZE - 1;
		int ret;

		memset(&raw, 0, sizeof(raw));
		raw.src_addr = NSP_SRC_ADDR;
		raw.src_port = ch->me;
		raw.dst_addr = NSP_DEV_ADDR;
		raw.dst_port = ch->svc;
		raw.data_size = (uint8_t)(chunk + 1);
		raw.data[0] = cmd;
		if (chunk)
			memcpy(raw.data + 1, data + offset, chunk);
		offset += chunk;
		ch->used = 1;
		if ((ret = nsp_send(calc, &raw)) || (ret = wait_ack(ch->me)))
			return ret;
		if (size > NSP_DATA_SIZE - 1) {
			update.max1 = (int)size;
			update.cnt1 = (int)offset;
			update.pbar();
		}
	} while (offset < size);
	return 0;
}

/*
 * Receive one reply of our session into ``out`` (command byte in ``*cmd``),
 * reassembling fragments until a short packet or ``expect`` bytes.
 */
static int chan_recv(struct chan *ch, uint8_t *cmd, GByteArray *out, uint32_t expect)
{
	g_byte_array_set_size(out, 0);
	for (;;) {
		NSPRawPacket in, ack;
		int ret;

		memset(&in, 0, sizeof(in));
		if ((ret = nsp_recv(calc, &in)))
			return ret == ERROR_READ_TIMEOUT ? E_BUSY : ret;
		if (is_ack_port(in.src_port))
			continue; /* stray ACK */
		if (in.src_port != ch->svc || in.dst_port != ch->me) {
			answer_packet(&in);
			continue;
		}
		memset(&ack, 0, sizeof(ack));
		ack.data_size = 2;
		ack.src_addr = NSP_SRC_ADDR;
		ack.src_port = NSP_PORT_PKT_ACK2;
		ack.dst_addr = NSP_DEV_ADDR;
		ack.dst_port = in.src_port;
		ack.data[0] = (uint8_t)(in.dst_port >> 8);
		ack.data[1] = (uint8_t)(in.dst_port & 0xFF);
		if ((ret = nsp_send(calc, &ack)))
			return ret;
		if (!in.data_size)
			continue;
		*cmd = in.data[0];
		g_byte_array_append(out, in.data + 1, in.data_size - 1u);
		if (expect) {
			update.max1 = (int)expect;
			update.cnt1 = (int)out->len;
			update.pbar();
		}
		if (in.data_size < NSP_DATA_SIZE || (expect && out->len >= expect))
			return 0;
	}
}

/* "FF status" reply: 0 = success, else E_CALC_STATUS + status. */
static int fm_recv_status(void)
{
	GByteArray *b = g_byte_array_new();
	uint8_t cmd = 0;
	int ret = chan_recv(&fm_chan, &cmd, b, 0);

	if (!ret)
		ret = (cmd != FM_STATUS || !b->len) ? E_PROTOCOL : (b->data[0] ? E_CALC_STATUS + b->data[0] : 0);
	g_byte_array_free(b, TRUE);
	return ret;
}

/* Path encoding of libticalcs put_str(): NUL-terminated, zero-padded to 9 bytes. */
static void put_path(GByteArray *b, const char *path)
{
	size_t len = strlen(path);
	static const uint8_t zeros[9] = {0};

	g_byte_array_append(b, (const uint8_t *)path, (guint)len);
	g_byte_array_append(b, zeros, len < 8 ? (guint)(9 - len) : 1);
}

/* Disconnect from a service (packet from port 0x40DE, payload = our port, like libticalcs). */
static void chan_close(struct chan *ch)
{
	NSPRawPacket raw;

	if (!ch->used)
		return;
	ch->used = 0;
	memset(&raw, 0, sizeof(raw));
	raw.src_addr = NSP_SRC_ADDR;
	raw.src_port = NSP_PORT_DISCONNECT;
	raw.dst_addr = NSP_DEV_ADDR;
	raw.dst_port = ch->svc;
	raw.data_size = 2;
	raw.data[0] = (uint8_t)(ch->me >> 8);
	raw.data[1] = (uint8_t)(ch->me & 0xFF);
	if (!nsp_send(calc, &raw))
		wait_ack(ch->me);
	answer_unsolicited();
}

/*
 * After a transport failure (timeout, unexpected packet) the session state is
 * unknown: start a new one next time. A status reply from the calculator
 * ("FF xx", e.g. file not found) is a clean answer and keeps the session:
 * closing and reopening right after it left the file service unanswered for
 * ~45 s in tests on OS 4.5.5.
 */
static int fm_fail(int ret, const char *what)
{
	if (ret < E_CALC_STATUS || ret >= E_CALC_STATUS + 256)
		chan_close(&fm_chan);
	return reply_error(ret, what);
}

#define REQUIRE_LINK() do { if (!calc) return reply_error(E_NOT_OPEN, "link is not open"); } while (0)

/* ---------- commands ---------- */

static int cmd_probe(void)
{
	int *pids = NULL, len = 0;
	int ret = ticables_get_usb_devices(&pids, &len);
	if (ret)
		return reply_error(ret, "USB probe failed");
	reply_begin();
	printf(",\"pids\":[");
	for (int i = 0; pids && pids[i]; i++)
		printf("%s%d", i ? "," : "", pids[i]);
	printf("]");
	reply_end();
	ticables_free_usb_devices(pids);
	return 0;
}

static uint64_t be64(const uint8_t *p)
{
	uint64_t v = 0;
	for (int i = 0; i < 8; i++)
		v = (v << 8) | p[i];
	return v;
}

/*
 * Device information over its own channel (service 0x4020): MODEL (0x02)
 * gives the product name, VERSION (0x01) the rest. Field offsets are those
 * of libticalcs calc_nsp.cc get_version().
 */
static int cmd_info(void)
{
	GByteArray *model = g_byte_array_new(), *ver = g_byte_array_new();
	uint8_t cmd = 0;
	int ret;

	REQUIRE_LINK();
	ret = chan_send(&di_chan, 0x02, NULL, 0);
	if (!ret)
		ret = chan_recv(&di_chan, &cmd, model, 0);
	if (!ret)
		ret = chan_send(&di_chan, 0x01, NULL, 0);
	if (!ret)
		ret = chan_recv(&di_chan, &cmd, ver, 0);
	if (!ret && ver->len < 110)
		ret = E_PROTOCOL;
	if (ret) {
		g_byte_array_free(model, TRUE);
		g_byte_array_free(ver, TRUE);
		chan_close(&di_chan);
		return reply_error(ret, "cannot read device information");
	}
	const uint8_t *d = ver->data;
	char name[65] = {0}, os[16], boot[16], boot2[16], id[29] = {0};
	memcpy(name, model->data, model->len < 64 ? model->len : 64);
	snprintf(os, sizeof(os), "%d.%d.%04d", d[36], d[37], (d[38] << 8) | d[39]);
	snprintf(boot, sizeof(boot), "%d.%d.%04d", d[40], d[41], (d[42] << 8) | d[43]);
	snprintf(boot2, sizeof(boot2), "%d.%d.%04d", d[44], d[45], (d[46] << 8) | d[47]);
	memcpy(id, d + 82, 28);
	reply_begin();
	printf(",\"product_name\":"); json_str(name);
	printf(",\"product_id\":"); json_str(id);
	printf(",\"os_version\":"); json_str(os);
	printf(",\"boot_version\":"); json_str(boot);
	printf(",\"boot2_version\":"); json_str(boot2);
	printf(",\"hw_version\":%u,\"device_type\":%u",
	       ((unsigned)d[48] << 24) | ((unsigned)d[49] << 16) | ((unsigned)d[50] << 8) | d[51], d[64]);
	printf(",\"flash_free\":%llu,\"flash_total\":%llu",
	       (unsigned long long)be64(d), (unsigned long long)be64(d + 8));
	printf(",\"ram_free\":%llu,\"ram_total\":%llu",
	       (unsigned long long)be64(d + 16), (unsigned long long)be64(d + 24));
	printf(",\"battery_ok\":%s,\"run_level\":%u", d[32] == 0x01 ? "false" : "true", d[53]);
	printf(",\"lcd_width\":%u,\"lcd_height\":%u,\"bpp\":%u,\"clock_speed\":%u",
	       (d[58] << 8) | d[59], (d[60] << 8) | d[61], d[62], d[35]);
	reply_end();
	g_byte_array_free(model, TRUE);
	g_byte_array_free(ver, TRUE);
	return 0;
}

/* Diagnostic: report what the calculator sends without being asked. */
static int cmd_listen(const char *seconds)
{
	GString *items = g_string_new(NULL);
	gint64 start = g_get_monotonic_time();
	gint64 limit = start + (gint64)(atof(seconds) * 1e6);
	unsigned int old;
	unsigned count = 0;

	REQUIRE_LINK();
	old = ticables_options_set_timeout(cable, 10);
	while (g_get_monotonic_time() < limit) {
		NSPRawPacket in;
		memset(&in, 0, sizeof(in));
		if (nsp_recv(calc, &in))
			continue; /* 1 s without packets */
		g_string_append_printf(items, "%s{\"t\":%.1f,\"src\":%u,\"dst\":%u,\"size\":%u,\"first\":%u}",
		                       count++ ? "," : "", (g_get_monotonic_time() - start) / 1e6,
		                       in.src_port, in.dst_port, in.data_size, in.data[0]);
		if (!is_ack_port(in.src_port))
			answer_packet(&in);
	}
	ticables_options_set_timeout(cable, old);
	reply_begin();
	printf(",\"packets\":[%s]", items->str);
	reply_end();
	g_string_free(items, TRUE);
	return 0;
}

static int cmd_list(const char *dir)
{
	GString *items = g_string_new(NULL);
	GByteArray *b = g_byte_array_new();
	unsigned count = 0;
	uint8_t cmd = 0;
	int ret;

	REQUIRE_LINK();
	put_path(b, dir);
	ret = chan_send(&fm_chan, 0x0D, b->data, b->len); /* DIRLIST_INIT */
	if (!ret)
		ret = fm_recv_status();
	while (!ret) {
		ret = chan_send(&fm_chan, 0x0E, NULL, 0); /* DIRLIST_NEXT */
		if (!ret)
			ret = chan_recv(&fm_chan, &cmd, b, 0);
		if (ret)
			break;
		if (cmd == FM_STATUS) {
			if (b->len && b->data[0] == 0x11) /* no more entries */
				break;
			ret = b->len ? E_CALC_STATUS + b->data[0] : E_PROTOCOL;
			break;
		}
		/* DIRLIST_ENT, parsed like libticalcs nsp_cmd_r_dir_enum_next(). */
		if (cmd != 0x10 || b->len < 2 || b->data[1] + 2u > b->len || b->data[1] + 2u < 10) {
			ret = E_PROTOCOL;
			break;
		}
		unsigned end = b->data[1] + 2u, o = end - 10;
		char name[256] = {0};
		memcpy(name, b->data + 2, end - 2 < sizeof(name) - 1 ? end - 2 : sizeof(name) - 1);
		uint32_t size = ((uint32_t)b->data[o] << 24) | ((uint32_t)b->data[o + 1] << 16) |
		                ((uint32_t)b->data[o + 2] << 8) | b->data[o + 3];
		g_string_append(items, count++ ? ",{\"name\":" : "{\"name\":");
		json_append(items, name);
		g_string_append_printf(items, ",\"size\":%u,\"type\":%u}", size, b->data[o + 8]);
	}
	if (!ret)
		ret = chan_send(&fm_chan, 0x0F, NULL, 0); /* DIRLIST_DONE */
	if (!ret)
		ret = fm_recv_status();
	g_byte_array_free(b, TRUE);
	if (ret) {
		g_string_free(items, TRUE);
		return fm_fail(ret, "cannot list folder");
	}
	reply_begin();
	printf(",\"items\":[%s]", items->str);
	reply_end();
	g_string_free(items, TRUE);
	return 0;
}

static int cmd_get(const char *remote, const char *local)
{
	GByteArray *b = g_byte_array_new();
	static const uint8_t one = 0x01, ok_status = 0x00;
	uint32_t size = 0;
	uint8_t cmd = 0;
	int ret;

	REQUIRE_LINK();
	reset_progress();
	g_byte_array_append(b, &one, 1);
	put_path(b, remote);
	ret = chan_send(&fm_chan, 0x07, b->data, b->len); /* GET_FILE */
	if (!ret)
		ret = chan_recv(&fm_chan, &cmd, b, 0);
	if (!ret) {
		if (cmd == FM_STATUS)
			ret = b->len ? E_CALC_STATUS + b->data[0] : E_PROTOCOL;
		else if (cmd != 0x03 || b->len < 14) /* PUT_FILE: name and size */
			ret = E_PROTOCOL;
		else
			size = ((uint32_t)b->data[10] << 24) | ((uint32_t)b->data[11] << 16) |
			       ((uint32_t)b->data[12] << 8) | b->data[13];
	}
	if (!ret)
		ret = chan_send(&fm_chan, 0x04, NULL, 0); /* OK */
	if (!ret && size) {
		ret = chan_recv(&fm_chan, &cmd, b, size);
		if (!ret && (cmd != 0x05 || b->len != size)) /* CONTENTS */
			ret = E_PROTOCOL;
	}
	if (!ret)
		ret = chan_send(&fm_chan, FM_STATUS, &ok_status, 1);
	if (ret) {
		g_byte_array_free(b, TRUE);
		return fm_fail(ret, "download failed");
	}
	answer_unsolicited();

	/* Atomic write: temporary file in the same folder, then rename. */
	char *tmp = g_strdup_printf("%s.part", local);
	FILE *f = fopen(tmp, "wb");
	int ok = f && (size == 0 || fwrite(b->data, 1, size, f) == size);
	if (f && fclose(f))
		ok = 0;
	if (ok && rename(tmp, local))
		ok = 0;
	int err = errno;
	g_byte_array_free(b, TRUE);
	if (!ok) {
		unlink(tmp);
		g_free(tmp);
		return reply_error(E_LOCAL_IO, strerror(err));
	}
	g_free(tmp);
	reply_begin();
	printf(",\"size\":%u", size);
	reply_end();
	return 0;
}

/* Untested with hardware (no writes to the calculator were allowed yet). */
static int cmd_put(const char *local, const char *remote)
{
	gchar *data = NULL;
	gsize size = 0;
	GError *gerr = NULL;
	GByteArray *b;
	static const uint8_t one = 0x01;
	uint8_t cmd = 0;
	int ret;

	REQUIRE_LINK();
	if (!g_file_get_contents(local, &data, &size, &gerr)) {
		ret = reply_error(E_LOCAL_IO, gerr->message);
		g_error_free(gerr);
		return ret;
	}
	if (size > UINT32_MAX) {
		g_free(data);
		return reply_error(E_TOO_BIG, "file too large");
	}
	reset_progress();
	b = g_byte_array_new();
	g_byte_array_append(b, &one, 1);
	put_path(b, remote);
	uint8_t be[4] = {(uint8_t)(size >> 24), (uint8_t)(size >> 16), (uint8_t)(size >> 8), (uint8_t)size};
	g_byte_array_append(b, be, 4);
	ret = chan_send(&fm_chan, 0x03, b->data, b->len); /* PUT_FILE */
	if (!ret)
		ret = chan_recv(&fm_chan, &cmd, b, 0);
	if (!ret && cmd == FM_STATUS)
		ret = b->len ? E_CALC_STATUS + b->data[0] : E_PROTOCOL;
	else if (!ret && cmd != 0x04) /* OK */
		ret = E_PROTOCOL;
	if (!ret)
		ret = chan_send(&fm_chan, 0x05, (const uint8_t *)data, (uint32_t)size); /* CONTENTS */
	if (!ret)
		ret = fm_recv_status();
	g_byte_array_free(b, TRUE);
	g_free(data);
	if (ret)
		return fm_fail(ret, "upload failed");
	answer_unsolicited();
	reply_begin();
	printf(",\"size\":%u", (unsigned)size);
	reply_end();
	return 0;
}

/* Delete file, create/delete folder and rename: one command + status (untested with hardware). */
static int simple_fm(const char *what, const char *a, const char *b2)
{
	GByteArray *b = g_byte_array_new();
	uint8_t cmd, flag;
	int ret;

	REQUIRE_LINK();
	if (!strcmp(what, "del")) { cmd = 0x09; flag = 0x01; }
	else if (!strcmp(what, "mkdir")) { cmd = 0x0A; flag = 0x03; }
	else if (!strcmp(what, "rmdir")) { cmd = 0x0B; flag = 0x03; }
	else { cmd = 0x21; flag = 0x01; }
	g_byte_array_append(b, &flag, 1);
	put_path(b, a);
	if (b2)
		put_path(b, b2);
	ret = chan_send(&fm_chan, cmd, b->data, b->len);
	if (!ret)
		ret = fm_recv_status();
	g_byte_array_free(b, TRUE);
	if (ret)
		return fm_fail(ret, "operation failed");
	reply_ok();
	return 0;
}

/* ---------- main loop ---------- */

static int dispatch(char **argv, int argc)
{
	const char *cmd = argv[0];
#define NEED(n) do { if (argc != (n) + 1) return reply_error(E_USAGE, "wrong number of arguments"); } while (0)

	if (!strcmp(cmd, "hello")) {
		reply_begin();
		printf(",\"version\":\"" TCM_LINK_VERSION "\"");
		reply_end();
		return 0;
	}
	if (!strcmp(cmd, "probe")) return cmd_probe();
	if (!strcmp(cmd, "open")) return link_open();
	if (!strcmp(cmd, "close")) { link_close(); reply_ok(); return 0; }
	if (!strcmp(cmd, "info")) return cmd_info();
	if (!strcmp(cmd, "list")) { NEED(1); return cmd_list(argv[1]); }
	if (!strcmp(cmd, "listen")) { NEED(1); return cmd_listen(argv[1]); }
	if (!strcmp(cmd, "get")) { NEED(2); return cmd_get(argv[1], argv[2]); }
	if (!strcmp(cmd, "put")) { NEED(2); return cmd_put(argv[1], argv[2]); }
	if (!strcmp(cmd, "del") || !strcmp(cmd, "mkdir") || !strcmp(cmd, "rmdir")) {
		NEED(1);
		return simple_fm(cmd, argv[1], NULL);
	}
	if (!strcmp(cmd, "rename")) { NEED(2); return simple_fm(cmd, argv[1], argv[2]); }
	return reply_error(E_USAGE, "unknown command");
#undef NEED
}

int main(void)
{
	char *line = NULL;
	size_t cap = 0;
	ssize_t n;

	/* stdout carries only JSON: glib prints INFO/DEBUG to stdout by default. */
	g_log_set_default_handler(log_to_stderr, NULL);
	ticables_library_init();
	ticalcs_library_init();

	while ((n = getline(&line, &cap, stdin)) > 0) {
		char *argv[MAX_ARGS + 2] = {0};
		int argc = 0;

		line[strcspn(line, "\r\n")] = 0;
		char *save = NULL;
		char *id = strtok_r(line, "\t", &save);
		if (!id)
			continue;
		current_id = id;
		for (char *tok; argc < MAX_ARGS + 1 && (tok = strtok_r(NULL, "\t", &save));)
			argv[argc++] = tok;
		if (!argc) {
			reply_error(E_USAGE, "missing command");
			continue;
		}
		if (!strcmp(argv[0], "quit")) {
			reply_ok();
			break;
		}
		dispatch(argv, argc);
		progress_enabled = 0;
	}
	free(line);
	link_close();
	ticalcs_library_exit();
	ticables_library_exit();
	return 0;
}
