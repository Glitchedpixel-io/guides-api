"""HTTP route handlers.

Every router is constructed with ``route_class=QuietClientErrorRoute``, with no exceptions:
without it, each ordinary 404 is recorded by Logfire's instrumentation as a server-side
exception and files an issue.
"""
