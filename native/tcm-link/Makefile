# Builds the tcm-link USB helper against the system libticalcs2 (TiLP).
CC ?= gcc
CFLAGS ?= -O2 -Wall -Wextra
PKGS = ticalcs2 ticables2 glib-2.0

tcm-link: tcm_link.c
	$(CC) $(CFLAGS) -o $@ $< $$(pkg-config --cflags --libs $(PKGS))

clean:
	rm -f tcm-link

.PHONY: clean
