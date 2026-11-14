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
 *   resync                    USB reset + address assignment (recovery)
 *   quit                      close the link and exit
 *
 * Only the operations of the file management service (0x4060) used by
 * libticalcs itself are called. Remote paths are absolute ("/MyLib/x.tns")
 * and keep their real extension, unlike ticalcs_calc_get_dirlist().
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

static CableHandle *cable;
static CalcHandle *calc;
static CalcUpdate update;
static const char *current_id = "0";
static int progress_enabled; /* only get/put report progress */

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

static int reply_error(int code, const char *fallback)
{
	char *msg = NULL;

	if (code < E_USAGE) {
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

static void link_close(void)
{
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
 * Bring the link back to a clean state: USB reset plus NSP address
 * assignment (the first half of ticalcs_calc_isready(), without its 4 s
 * LOGIN wait).
 *
 * Needed after every download. Once a get session is closed, OS >= 1.7
 * sends an unsolicited packet (libticalcs recv_var() calls it "martian").
 * Measured on CX CAS OS 4.5.5, with libticalcs, libnspire and this helper:
 * ignoring, ACKing or NACKing that packet all leave the file service
 * (0x4060) unanswered; the device info service keeps working. After a
 * reset it recovered once (~20 s), but another time it stayed blocked for
 * minutes. The client retries after resync; see docs/USB-PROTOCOL.md.
 */
static int resync(void)
{
	int ret = nsp_addr_request(calc);
	if (!ret)
		ret = nsp_addr_assign(calc, NSP_DEV_ADDR);
	return ret;
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

static int cmd_info(void)
{
	CalcInfos ci;
	int ret;

	REQUIRE_LINK();
	memset(&ci, 0, sizeof(ci));
	ret = ticalcs_calc_get_version(calc, &ci);
	if (ret)
		return reply_error(ret, "cannot read device information");
	reply_begin();
	printf(",\"product_name\":"); json_str(ci.product_name);
	printf(",\"product_id\":"); json_str(ci.product_id);
	printf(",\"os_version\":"); json_str(ci.os_version);
	printf(",\"boot_version\":"); json_str(ci.boot_version);
	printf(",\"boot2_version\":"); json_str(ci.boot2_version);
	printf(",\"hw_version\":%u,\"device_type\":%u", ci.hw_version, ci.device_type);
	printf(",\"flash_free\":%llu,\"flash_total\":%llu",
	       (unsigned long long)ci.flash_free, (unsigned long long)ci.flash_phys);
	printf(",\"ram_free\":%llu,\"ram_total\":%llu",
	       (unsigned long long)ci.ram_free, (unsigned long long)ci.ram_phys);
	printf(",\"battery_ok\":%s,\"run_level\":%u", ci.battery ? "true" : "false", ci.run_level);
	printf(",\"lcd_width\":%u,\"lcd_height\":%u,\"bpp\":%u,\"clock_speed\":%u",
	       ci.lcd_width, ci.lcd_height, ci.bits_per_pixel, ci.clock_speed);
	reply_end();
	return 0;
}

static int cmd_list(const char *dir)
{
	int ret;
	GString *items = g_string_new(NULL);
	unsigned count = 0;

	REQUIRE_LINK();
	ret = nsp_session_open(calc, NSP_SID_FILE_MGMT);
	if (!ret)
		ret = nsp_cmd_s_dir_enum_init(calc, dir);
	if (!ret)
		ret = nsp_cmd_r_dir_enum_init(calc);
	while (!ret) {
		char name[1024] = {0};
		uint32_t size = 0;
		uint8_t type = 0;

		ret = nsp_cmd_s_dir_enum_next(calc);
		if (!ret)
			ret = nsp_cmd_r_dir_enum_next(calc, name, &size, &type);
		if (ret == TCM_ERR_EOT) {
			ret = 0;
			break;
		}
		if (ret)
			break;
		/* Print into a buffer: a failure mid-listing must not emit a partial reply. */
		g_string_append(items, count++ ? ",{\"name\":" : "{\"name\":");
		json_append(items, name);
		g_string_append_printf(items, ",\"size\":%u,\"type\":%u}", size, type);
	}
	if (!ret) {
		ret = nsp_cmd_s_dir_enum_done(calc);
		if (!ret)
			ret = nsp_cmd_r_dir_enum_done(calc);
	}
	nsp_session_close(calc);
	if (ret) {
		g_string_free(items, TRUE);
		return reply_error(ret, "cannot list folder");
	}
	reply_begin();
	printf(",\"items\":[%s]", items->str);
	reply_end();
	g_string_free(items, TRUE);
	return 0;
}

static int cmd_get(const char *remote, const char *local)
{
	uint32_t size = 0;
	uint8_t *data = NULL;
	int ret;

	REQUIRE_LINK();
	reset_progress();
	ret = nsp_session_open(calc, NSP_SID_FILE_MGMT);
	if (!ret)
		ret = nsp_cmd_s_get_file(calc, remote);
	if (!ret)
		ret = nsp_cmd_r_get_file(calc, &size);
	if (!ret)
		ret = nsp_cmd_s_file_ok(calc);
	if (!ret && size)
		ret = nsp_cmd_r_file_contents(calc, &size, &data);
	if (!ret)
		ret = nsp_cmd_s_status(calc, NSP_ERR_OK);
	nsp_session_close(calc);
	resync();
	if (ret) {
		g_free(data);
		return reply_error(ret, "download failed");
	}

	/* Atomic write: temporary file in the same folder, then rename. */
	char *tmp = g_strdup_printf("%s.part", local);
	FILE *f = fopen(tmp, "wb");
	int ok = f && (size == 0 || fwrite(data, 1, size, f) == size);
	if (f && fclose(f))
		ok = 0;
	if (ok && rename(tmp, local))
		ok = 0;
	if (!ok) {
		int err = errno;
		unlink(tmp);
		g_free(tmp);
		g_free(data);
		return reply_error(E_LOCAL_IO, strerror(err));
	}
	g_free(tmp);
	g_free(data);
	reply_begin();
	printf(",\"size\":%u", size);
	reply_end();
	return 0;
}

static int cmd_put(const char *local, const char *remote)
{
	gchar *data = NULL;
	gsize size = 0;
	GError *gerr = NULL;
	uint8_t status = 0;
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
	ret = nsp_session_open(calc, NSP_SID_FILE_MGMT);
	if (!ret)
		ret = nsp_cmd_s_put_file(calc, remote, (uint32_t)size);
	if (!ret)
		ret = nsp_cmd_r_put_file(calc);
	if (!ret)
		ret = nsp_cmd_s_file_contents(calc, (uint32_t)size, (uint8_t *)data);
	if (!ret)
		ret = nsp_cmd_r_status(calc, &status);
	nsp_session_close(calc);
	g_free(data);
	if (ret)
		return reply_error(ret, "upload failed");
	reply_begin();
	printf(",\"size\":%u", (unsigned)size);
	reply_end();
	return 0;
}

/* Delete file, create/delete folder and rename share the same shape. */
static int simple_fm(const char *what, const char *a, const char *b)
{
	int ret;

	REQUIRE_LINK();
	ret = nsp_session_open(calc, NSP_SID_FILE_MGMT);
	if (!ret) {
		if (!strcmp(what, "del")) {
			ret = nsp_cmd_s_del_file(calc, a);
			if (!ret) ret = nsp_cmd_r_del_file(calc);
		} else if (!strcmp(what, "mkdir")) {
			ret = nsp_cmd_s_new_folder(calc, a);
			if (!ret) ret = nsp_cmd_r_new_folder(calc);
		} else if (!strcmp(what, "rmdir")) {
			ret = nsp_cmd_s_del_folder(calc, a);
			if (!ret) ret = nsp_cmd_r_del_folder(calc);
		} else {
			ret = nsp_cmd_s_rename_file(calc, a, b);
			if (!ret) ret = nsp_cmd_r_rename_file(calc);
		}
	}
	nsp_session_close(calc);
	if (ret)
		return reply_error(ret, "operation failed");
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
	if (!strcmp(cmd, "resync")) {
		REQUIRE_LINK();
		int ret = resync();
		if (ret)
			return reply_error(ret, "resync failed");
		reply_ok();
		return 0;
	}
	if (!strcmp(cmd, "close")) { link_close(); reply_ok(); return 0; }
	if (!strcmp(cmd, "info")) return cmd_info();
	if (!strcmp(cmd, "list")) { NEED(1); return cmd_list(argv[1]); }
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
