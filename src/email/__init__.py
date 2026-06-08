"""Email parsing helpers (threading, body normalization).

The IMAP/SMTP transport and the agent tools live elsewhere; this
package isolates the pure parsing logic so it can be exercised
without the rest of the email stack.
"""
