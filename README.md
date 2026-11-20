# LEX AI · Evidence Workbench

An email says a customer accepted an equipment delivery. The dispatch record gives a time. The signed acceptance is missing. LEX shows a reviewer exactly which source supports each statement and keeps that gap visible in the final packet.

This edition runs a fictional case on a local Python and SQLite application. A deterministic simulation challenges the initial claim, narrows its wording and records the remaining uncertainty. EXCALIBUR assembles an HTML packet containing the draft, cited lines, findings and exhibits.

## Try the review

Use Python 3.11 or later. From this directory, run:

```sh
python3 lex.py
```

Open `http://127.0.0.1:8765` in a browser.

1. Click **Load fictional case**. Read line L2 of the email and compare it with the dispatch export. The email reports acceptance. The export establishes the dispatch time.
2. Click **Run simulation**. Under **Review loop**, inspect the original objection, the revised wording and the outstanding request for a signed record.
3. Click **Assemble review packet**, then **Open rendered packet**. Return to the workbench, acknowledge the exact packet and approve it for local review. The approval refers to the packet digest and the source versions used to build it.
4. Open **Sources** and choose **Simulate source change** for the fictional email. Return to **EXCALIBUR**. The earlier packet is marked **STALE**, and its active approval is cleared. Its previous approval remains visible in the audit history.

The app uses the local `data/` folder for SQLite, source text and generated packets. To try a separate case, start the app with a fresh directory using `python3 lex.py --data /path/to/new-demo`. Stop the server with Ctrl+C.

## Verify the behaviour

```sh
python3 -m unittest discover -s tests -v
```

The 17 engine tests cover source integrity, exact citations, duplicate and derivative evidence, review limits, packet approval and invalidation. Ten additional tests exercise the structured review importer, including rollback of incomplete reviews and rejection of outdated evidence snapshots. The example bundle in `tests/test_review_import.py` shows the accepted format.

## Operating assumptions

This is a single-user prototype for fictional records. The person running it controls the files and database. A matching hash establishes byte consistency. A valid citation resolves to a source line. Judging whether that line supports the conclusion remains the reviewer's responsibility.
