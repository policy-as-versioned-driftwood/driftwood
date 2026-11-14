# API image evidence

Corrected 2026-10-03 (ticket 154): the API's upstream README called it "the good citizen".
The 2026-09-25 scan found 8 HIGH CVEs in Go 1.26.5, on end-of-support Alpine 3.20.10.
The served manifest now names the transferred app repo's existing v1.0.1 image by its
anonymously verified GHCR digest. A new inventory scan is required to establish the CVEs
of that image; a current dependency declaration does not establish a clean shipped image.
