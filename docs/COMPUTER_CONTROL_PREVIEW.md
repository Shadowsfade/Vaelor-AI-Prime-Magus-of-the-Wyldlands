# Computer Control preview: Windows acceptance guide

The desktop package bundles Python and the web UI. Keep the complete extracted
Vaelor folder together; run Vaelor.exe. Windows WebView2 and a configured model
backend are still required.

## Try the controls

1. Open a disposable Notepad document on the primary display.
2. In Computer Control, choose Find vision models. This inspects installed Ollama
   metadata without downloading or loading a model. The suggested smallest model
   is a size heuristic; it does not promise fast inference or GPU fit.
3. Open the task you want to authorize in Task Center. Its ID fills the computer
   task field. Check that this is the intended task.
4. Refresh windows and select the disposable Notepad window. Window scope restricts
   input; observations still include the entire primary display.
5. Choose Allow task for 5 minutes, then Bring selected window forward. If Windows
   refuses focus, bring it forward manually. Focus does not mean the task succeeded.
6. Ask the task to observe the screen and type a harmless test sentence into the
   blank document. Confirm the result yourself. This is a manual acceptance test,
   not a claim that desktop input has already passed end-to-end validation.
7. Choose Stop computer control when finished. Holding Escape also blocks the next
   action. The session expires and is limited to 100 input/focus actions.

## Expected refusals

- Another task cannot use the session. Closing the selected window revokes it.
- Input outside the selected window, or through an overlapping window, is rejected.
- Changed screen pixels or a changed foreground invalidate observations. Observe
  again before input; animated content can cause repeated refusals.
- Vision support must be verified from Ollama metadata before a screenshot is sent.
  An unverified fallback model cannot receive it. LM Studio vision verification is
  not implemented in this preview.
- Slow vision analysis rechecks the frame before granting a fresh input snapshot.
  The synthetic-image test on this Windows host took about 101 seconds.

## Task durability

Task state is locked across processes and atomically replaced. A second process
must not interrupt a worker with an unexpired lease. Expired leases are recovered
by supervisor polling; uncertain mutations require verification before retry.
Invalid JSON is preserved and reported as an error, not reset to an empty queue.

Automated coverage includes three-process claim and approval races, concurrent
record creation, corrupt-state preservation, live-lease preservation, and expired
mutation recovery. Native mouse/keyboard goal completion remains a manual test.
