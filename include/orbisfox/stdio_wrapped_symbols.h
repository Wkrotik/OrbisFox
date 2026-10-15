#pragma once
// Kept in one machine-readable list for native linker and regression checks.
#define ORBISFOX_STDIO_WRAPPED_SYMBOLS \
  "printf", "fprintf", "vprintf", "puts", "putchar", "perror", \
  "vfprintf", "fwrite", "fflush", "fputc", "putc", "fputs", \
  "fopen", "fdopen", "freopen", "fclose", "setvbuf", "setbuf", \
  "fread", "fgets", "fgetc", "getc", "ungetc", "vfscanf", \
  "fseek", "ftell", "fseeko", "ftello", "rewind", \
  "clearerr", "feof", "ferror"
