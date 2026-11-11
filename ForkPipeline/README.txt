ForkPipeline - the WAAM logger package
(64-bit Windows, zero installs - everything runs from this folder)

WHAT IS IN THE FOLDER

  QuantumXGuiFork.exe  - the logger. Type the QuantumX address in the
                         IP box (e.g. 192.168.137.250), press CONNECT,
                         then START. The DAQ channels c1..c8 fill the
                         channel windows.
  --demo               - no hardware needed: QuantumXGuiFork.exe --demo
                         (synthetic channels - try the trigger rules on
                         them).
  start_bench.bat      - starts the logger AND both watchers together
                         (pose_watcher + welder_watcher + the logger).
  pose_watcher\        - the robot pose + welder words sender. Fills
                          its own conf on first run - edit ip + arc-bit
                          in pose_watcher.conf, then start it again.
  scripts\             - the trigger tools, WITH their sources:
                           bell          - a test sound (also bell.py)
                           img_cap1      - a camera, one shot per run
                           ir_cap1       - an IR camera, one shot per run
                           kw_grapher    - the live power graph
                           streams       - saves the stream column
                           notify        - mail on a trigger
                            welder_watcher- the Fronius welder watcher:
                          THE W-WORD (the stream column, ~2 lines/s):
                            W,<I>,<V>,<WFS>,<kW>,<energy>
                          the welder's own display set, verbatim.
                          Between arcs it holds the last arc's values
                          (the screen's memory - frozen is the truth,
                          not a fault).
                          THE R-WORD (the events column, the recipe
                          witness): R,<synergy>,<job>,<Iprog>,<Vprog>,
                          <arclen>,<dyn> - WHAT WAS PROGRAMMED, beside
                          WHAT RAN. Repeats every 5 s so every file
                          carries it; fires immediately if anyone
                          changes job or parameters - even mid-weld.
                          Values are the machine's own floats - any
                          scaling happens later, in analysis, never
                          here.
                          Every tool builds in place: the build*.cmd
                          beside the sources uses the in-box C# compiler
                          - nothing to install, ever.

THE TRIGGER GUI (the gear beside "Triggers")

  A rule = IF <condition> IS <value> RUN <tool>. Conditions: channels
  (c1..c8, lists like c1,c2), on_start (a session begins), on_stop
  (the interpass - after a stop), timer, counter, recv words (UDP
  5551: send "start" / "stop" from anything), file tails
  (file name.log[3]). The ? button is the full manual - grammar,
  fire modes, and examples that work on the first try.

WHERE THE DATA LANDS

  2026\MM\DD\<session>\ - the CSV (one per session, named in the file
  box) plus every fired tool's own files beside it (the tools learn
  the folder through the LOGGER_LOG_DIR environment variable).
  The session box iterates (session1, session2...); a new day starts
  fresh; an occupied name is never overwritten - the box moves on.

  The CSV is yours - free for all. Python, Excel, any grapher you
  like: read the file, build whatever you want on top of it. The
  trigger GUI can even wire your tool to the data for you:
  file a.csv[3] (a file-tail condition on a column) run yourprogram.

CONFS

  Every conf self-creates on first run, with comments inside it.
  Delete a conf to reset that tool. settings.conf holds the logger's
  own window state.

The build stamp lives in the window banner, top left (fork2026-...).
