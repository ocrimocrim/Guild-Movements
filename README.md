# Guild movements

The scheduled workflow tracks visible players and preserves the last known guild of players absent from a scan. It sends each change separately and checkpoints `players.json` to Git after each confirmed delivery. A missing webhook, HTTP error, empty snapshot, invalid state, or failed checkpoint fails the run and stops further posts. Configure the `DISCORD_WEBHOOK_URL` Actions secret before running it.

## BUFFER recovery

Commit `a96dc4e3cd6b4ae765f92a515c10dc3e7bffaf3e` added BUFFER to Momentum. The original workflow logged a failed delivery. `buffer-recovery.json` records the exact lost message separately without changing player data. After merging the fix and correcting the webhook, open Actions → Guild Tracker → Run workflow on `main`, select `replay-buffer`, and run it once. The workflow commits the delivery marker after Discord confirms the post; a later replay sees that marker and does nothing. Normal scheduled runs do not send this recovery message.

## Delivery limitations

Discord and Git do not share a transaction. If Discord accepts a post but its response is lost, or the runner stops or the Git push fails before the checkpoint reaches GitHub, the next run may post the same event again. After an ambiguous failure, inspect Discord and the workflow log before retrying; reconcile the corresponding player state or recovery marker if the message is already present. Workflow concurrency prevents overlapping tracker runs, but unrelated writes to the branch can still cause a push failure. A snapshot-based tracker also cannot observe changes that occur and reverse between scans.

Run the simulated tests with `python -m unittest discover -s tests -v` after installing `requests` and `beautifulsoup4`. The tests do not send Discord messages.
