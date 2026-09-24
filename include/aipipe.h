/* NetHack 3.6	aipipe.h	*/
/* Copyright (c) 2026.  NetHack may be freely redistributed.  See license. */

/* Structured control channel for an external controller; see aipipe.c. */

#ifndef AIPIPE_H
#define AIPIPE_H

extern void NDECL(aipipe_install);
extern int NDECL(aipipe_getch);
extern void FDECL(aipipe_context, (const char *, const char *, const char *));
extern void FDECL(aipipe_more, (BOOLEAN_P));

#endif /* AIPIPE_H */
