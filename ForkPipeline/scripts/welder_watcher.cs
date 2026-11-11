// welder_watcher - the Fronius socket watcher (a lonely companion).
//
// Watches the SmartManager speedNet socket (robot-dev's v9 protocol:
// cell-2/fronius-socket/2026-10-09-tag-registry.md) and speaks the logger's
// two UDP channels, exactly like pose_watcher watches the robot:
//
//   stream port (5552):  W,<I>,<V>,<WFS>,<kW>,<energy> - one W-word per cycle,
//                       the display quintet AS THE MACHINE PUBLISHES IT
//                       (raw, never rescaled; the 4e30-class sentinel = the
//                       machine's own "no data" word, logged verbatim).
//   rx port (5551):     werr <value> / werr clear (the detailed-error
//                       channel 701 waking / sleeping)
//                       NOTHING ELSE gets a word: the display set is the
//                       screen's MEMORY (frozen through interpasses - the v9
//                       capture has zero sub-10A samples), so no arc witness
//                       here; the arc truth = the robot's words (RX:start /
//                       the delayed stop). The energy counter reset = the
//                       machine's internal scorekeeper (not watched either).
//
// The logger needs nothing: the stream port writes any payload, the rx port
// takes any word (events + rules). The contract: stream_word_reference.md.
//
// A CONSOLE TWIN of pose_watcher (user 2026-10-10: "why does it not start in
// a command line like posewatcher?"): start_bench.bat launches it minimized,
// the console scrolls one status line per cycle, closing the console or
// "welder_watcher.exe --kill" = clean death (the --kill lives in the exe;
// the old wrapper bats are retired - user 2026-10-11: "confusion and
// ambiguity is not something we do here"). The watcher watches: reconnects
// forever (the welder may power-cycle); no files of its own beyond the trail
// log beside the exe. One instance (mutex).
//
// Build: build_welder.cmd (in-box csc, zero installs).

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

internal class WelderWatcher
{
    // ---- conf (welder_watcher.conf beside the exe) ----
    private string _ip = "192.168.137.15";
    private string _user = "admin";
    private string _pass = "admin";
    private string _rxHost = "127.0.0.1";
    private int _rxPort = 5551;
    private string _stHost = "127.0.0.1";
    private int _stPort = 5552;
    private double _cycleS = 2.0;

    // the watched tags (uid -> name; the display quintet + the error channel;
    // the unnamed seven stay out: proven permanently reserved on this machine)
    // (2026-10-13: 172 = DSP_RV_ENERGY probed - it carries a 4E+30 float
    // sentinel, garbage, not an energy. Dropped. The display energy (171) is
    // the live accumulating one; the "last weld" total rides the E-word.)
    // I before V (2026-10-14: the wire has ALWAYS been "W,<I>,<V>,..." -
    // the tag array's order. The declarations said V-first and the
    // declarations were wrong, not the watcher; all banked data is
    // I-first and stays coherent. The wire is the truth, the grammar
    // bends to it - never the reverse.)
    private static readonly int[] Tags = { 154, 155, 156, 170, 171, 701, 199, 13, 16, 44, 103, 104 };
    private static readonly string[] TagNames = { "I", "V", "WFS", "kW", "energy", "err",
        "synergy", "Iprog", "Vprog", "job", "arclen", "dyn" };

    private const double Sentinel = 1e29;   // |v| >= this = the machine's no-data class

    private readonly object _logLock = new object();

    private bool _kill;
    private static EventWaitHandle _killEvent;
    private static Mutex _once;

    // ---- the run state ----
    private ClientWebSocket _ws;
    private string _sid = "";
    private ushort _seq;
    private readonly Dictionary<int, double> _last = new Dictionary<int, double>();
    private string _lastR = "";   // the recipe witness word last sent ("" = re-declare at connect)
    private int _lastRSentTick;   // when the R last went out (the traceability heartbeat)
    private double _rHeartbeatS = 5;   // re-declare period: every file carries the witness
                                       // (user 2026-10-13: "5s is the beat" - travel 13.3 mm/s,
                                       // covers beads >= ~67 mm; 10 s left a 7.7 s file unwitnessed)
    private bool _errOn;
    private UdpClient _rxUc;
    private UdpClient _stUc;

    private static void Main(string[] args)
    {
        bool created;
        _once = new Mutex(true, "Local\\welder_watcher_once", out created);
        if (!created)
        {
            if (args.Length > 0 && args[0] == "--kill") SetKill();
            return;
        }
        GC.KeepAlive(_once);
        if (args.Length > 0 && args[0] == "--kill")
        {
            SetKill();   // no instance ran; clear any stale flag for the next start
            return;
        }
        bool killCreated;
        _killEvent = new EventWaitHandle(false, EventResetMode.ManualReset,
            "Local\\welder_watcher_kill", out killCreated);
        if (!killCreated) _killEvent.Reset();
        Console.Title = "welder_watcher";
        var t = new Thread(KillWatch);
        t.IsBackground = true;
        t.Start();
        Console.WriteLine("welder_watcher - the Fronius socket watcher (the console twin of pose_watcher)");
        var w = new WelderWatcher();
        w.LoadConf();
        w.Loop();
    }

    private static void KillWatch()
    {
        while (true)
        {
            if (_killEvent.WaitOne(250))
            {
                Console.WriteLine("killed (--kill) - exiting");
                Environment.Exit(0);
            }
        }
    }

    private static void SetKill()
    {
        bool created;
        var ev = new EventWaitHandle(false, EventResetMode.ManualReset,
            "Local\\welder_watcher_kill", out created);
        ev.Set();
    }

    // ---- conf ----
    private string ExeDir()
    {
        return Path.GetDirectoryName(Process.GetCurrentProcess().MainModule.FileName);
    }

    private void LoadConf()
    {
        try
        {
            string p = Path.Combine(ExeDir(), "welder_watcher.conf");
            if (!File.Exists(p))
            {
                File.WriteAllLines(p, new string[]
                {
                    "# welder_watcher.conf - his knobs. The watcher forwards the",
                    "# machine's own display set as W-words (raw, never rescaled):",
                    "#   W,<I>,<V>,<WFS>,<kW>,<energy> on the stream port,",
                    "#   werr <code> on the rx port (the display set never witnesses the arc).",
                    "welder_ip=" + _ip,
                    "username=" + _user,
                    "password=" + _pass,
                    "rx_host=" + _rxHost,
                    "rx_port=" + _rxPort,
                    "stream_host=" + _stHost,
                    "stream_port=" + _stPort,
                    "cycle_s=" + _cycleS.ToString(CultureInfo.InvariantCulture),
                    "# cycle_s = THE HERTZ (user 2026-10-12: 'It should come",
                    "# in 2 hz as the intended speed'): 2 = two W-words and",
                    "# two console lines per second. The poll heartbeat rides",
                    "# the same period (the server reaps silent clients).",
                    "r_heartbeat_s=" + _rHeartbeatS.ToString(CultureInfo.InvariantCulture),
                    "# r_heartbeat_s = the R-word re-declare period (user:",
                    "# 'I want it IN every file for traceability') - a file is",
                    "# guaranteed a witness when its length >= this period.",
                    "# default 5 (user: '5s is the beat'; travel 13.3 mm/s:",
                    "# NOTE: the display set is the screen's MEMORY - it freezes at",
                    "# the last arc's values through the interpass (never an arc witness)."
                });
            }
            foreach (string raw in File.ReadAllLines(p))
            {
                string line = raw.Trim();
                if (line.Length == 0 || line.StartsWith("#")) continue;
                int eq = line.IndexOf('=');
                if (eq <= 0) continue;
                string k = line.Substring(0, eq).Trim();
                string v = line.Substring(eq + 1).Trim();
                int n;
                double d;
                if (k == "welder_ip") _ip = v;
                else if (k == "username") _user = v;
                else if (k == "password") _pass = v;
                else if (k == "rx_host") _rxHost = v;
                else if (k == "rx_port" && int.TryParse(v, out n)) _rxPort = n;
                else if (k == "stream_host") _stHost = v;
                else if (k == "stream_port" && int.TryParse(v, out n)) _stPort = n;
                else if (k == "cycle_s" && double.TryParse(v, NumberStyles.Float, CultureInfo.InvariantCulture, out d)) _cycleS = d;
                else if (k == "r_heartbeat_s" && double.TryParse(v, NumberStyles.Float, CultureInfo.InvariantCulture, out d)) _rHeartbeatS = d;
            }
        }
        catch { }
    }

    private void Log(string s)
    {
        lock (_logLock)
        {
            try
            {
                File.AppendAllText(Path.Combine(ExeDir(), "welder_watcher.log"),
                    DateTime.Now.ToString("HH:mm:ss.fff") + " " + s + Environment.NewLine);
            }
            catch { }
        }
    }

    private void SetStatus(string s)
    {
        // THE STREAM (user 2026-10-12, restored by demand: "put it back to
        // a stream form... that stuff was gold for waiting on the weld
        // discussion"): one line per iteration, scrolling - the console is
        // the bench's campfire; the log file remains the record.
        Console.WriteLine(DateTime.Now.ToString("HH:mm:ss") + "  " + s.Replace("\r\n", "  "));
    }

    private void Die(string why)
    {
        _kill = true;
        try { if (_ws != null) ((IDisposable)_ws).Dispose(); } catch { }
        Log("death: " + why);
        Console.WriteLine(why + " - exiting");
        Environment.Exit(0);
    }

    // ---- the v9 protocol (ported from robot-dev's speednet_capture.py) ----
    private byte[] Frame(byte[] payload)
    {
        int t = payload.Length + 24;
        var b = new byte[4 + t];
        Buffer.BlockCopy(BitConverter.GetBytes((uint)t), 0, b, 0, 4);
        b[4] = 0x64;
        Buffer.BlockCopy(BitConverter.GetBytes(_seq), 0, b, 5, 2);
        b[7] = 0;
        Buffer.BlockCopy(payload, 0, b, 8, payload.Length);
        _seq++;
        return b;
    }

    private static byte[] StxString(string s)
    {
        byte[] body = Encoding.UTF8.GetBytes(s);
        var b = new byte[5 + body.Length];
        b[0] = 0x02;
        Buffer.BlockCopy(BitConverter.GetBytes((uint)body.Length), 0, b, 1, 4);
        Buffer.BlockCopy(body, 0, b, 5, body.Length);
        return b;
    }

    private byte[] SubscribePayload()
    {
        // 2026-10-12 (bench, live diagnosis): the welder's speedNet now
        // demands BOTH node types - <r> (read) AND <a> (active) - before a
        // tag flows. r-only = the server ACKs (F8=;) and then sends nothing:
        // the watcher connected, subscribed, starved, looped. Found by
        // probing the wire beside the watcher: with <a> added, the N-frames
        // pour in (N155=28.64, N170=8.005 idle displays). The official web
        // client (/speedNet/js/speedNet.js) subscribes exactly this shape.
        var sb = new StringBuilder("<notifications>");
        foreach (int uid in Tags) sb.Append("<r uid=\"").Append(uid).Append("\"/><a uid=\"").Append(uid).Append("\"/>");
        sb.Append("</notifications>");
        return Concat(Concat(Encoding.UTF8.GetBytes("F8,"), StxString(sb.ToString())), Encoding.UTF8.GetBytes(";"));
    }

    private static byte[] Concat(byte[] a, byte[] b)
    {
        var r = new byte[a.Length + b.Length];
        Buffer.BlockCopy(a, 0, r, 0, a.Length);
        Buffer.BlockCopy(b, 0, r, a.Length, b.Length);
        return r;
    }

    private static List<byte[]> ParseFrames(byte[] buf, int len)
    {
        var outp = new List<byte[]>();
        int v = 0;
        while (v + 8 <= len)
        {
            uint t = BitConverter.ToUInt32(buf, v);
            int total = 4 + (int)t;
            if (total < 8 || v + total > len) break;
            int plStart = v + 8;
            int plLen = (int)t - 24;
            if (plLen > 0)
            {
                var pl = new byte[plLen];
                Buffer.BlockCopy(buf, plStart, pl, 0, plLen);
                outp.Add(pl);
            }
            v += total;
        }
        return outp;
    }

    private static Dictionary<int, double> ParseValues(byte[] pl)
    {
        var vals = new Dictionary<int, double>();
        int i = 0;
        while (i < pl.Length)
        {
            char c = (char)pl[i];
            if ((c == 'G' || c == 'N') && i + 1 < pl.Length)
            {
                int j = i + 1;
                if ((char)pl[j] == 'E') j++;
                int idStart = j;
                while (j < pl.Length && (char)pl[j] >= '0' && (char)pl[j] <= '9') j++;
                if (j > idStart && j < pl.Length && (char)pl[j] == '=')
                {
                    if (j + 5 <= pl.Length && (char)pl[j + 5] == ';')
                    {
                        int uid = int.Parse(Encoding.ASCII.GetString(pl, idStart, j - idStart), CultureInfo.InvariantCulture);
                        double fv = BitConverter.ToSingle(pl, j + 1);
                        if (!vals.ContainsKey(uid)) vals[uid] = fv;
                        i = j + 6;
                        continue;
                    }
                }
            }
            i++;
        }
        return vals;
    }

    private string Login()
    {
        var req = (HttpWebRequest)WebRequest.Create("https://" + _ip + "/login");
        req.Method = "POST";
        req.ContentType = "application/x-www-form-urlencoded";
        req.CookieContainer = new CookieContainer();
        byte[] body = Encoding.ASCII.GetBytes("username=" + Uri.EscapeDataString(_user) + "&password=" + Uri.EscapeDataString(_pass));
        req.ContentLength = body.Length;
        using (var s = req.GetRequestStream()) s.Write(body, 0, body.Length);
        using (var resp = (HttpWebResponse)req.GetResponse())
        {
            foreach (Cookie c in resp.Cookies)
            {
                if (c.Name == "sessionid") return c.Value;
            }
            string sc = resp.Headers["Set-Cookie"];
            if (sc != null)
            {
                int i = sc.IndexOf("sessionid=");
                if (i >= 0)
                {
                    int j = sc.IndexOf(';', i);
                    return j > i ? sc.Substring(i + 10, j - i - 10) : sc.Substring(i + 10);
                }
            }
        }
        throw new Exception("no sessionid in login response");
    }

    private ClientWebSocket Connect()
    {
        var ws = new ClientWebSocket();
        ws.Options.AddSubProtocol("binary");
        ws.Options.SetRequestHeader("Cookie", "sessionid=" + _sid);
        ws.ConnectAsync(new Uri("wss://" + _ip + "/WSspeedNet"), CancellationToken.None).Wait(5000);
        _seq = 0;
        ws.SendAsync(new ArraySegment<byte>(Frame(SubscribePayload())), WebSocketMessageType.Binary, true, CancellationToken.None).Wait(5000);
        return ws;
    }

    private void SendWord(string word)
    {
        try
        {
            if (_rxUc == null) _rxUc = new UdpClient();
            byte[] b = Encoding.ASCII.GetBytes(word);
            _rxUc.Send(b, b.Length, _rxHost, _rxPort);
            Log("word: " + word);
        }
        catch (Exception ex) { Log("word send failed: " + ex.Message); }
    }

    private void SendStream(string payload)
    {
        try
        {
            if (_stUc == null) _stUc = new UdpClient();
            byte[] b = Encoding.ASCII.GetBytes(payload);
            _stUc.Send(b, b.Length, _stHost, _stPort);
        }
        catch { }
    }

    private static string F6(double v)
    {
        return v.ToString("G6", CultureInfo.InvariantCulture);
    }

    // ---- the main loop (reconnect-by-design, the watcher watches) ----
    private void Loop()
    {
        ServicePointManager.ServerCertificateValidationCallback = delegate { return true; };
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
        int starved = 0;
        byte[] buf = new byte[65536];
        Task<WebSocketReceiveResult> awaiting = null;   // the single outstanding receive, kept across cycles

        while (!_kill)
        {
            try
            {
                Log("login...");
                _sid = Login();
                _ws = Connect();
                    starved = 0;
                    SetStatus("connected " + _ip + " - watching");
                    Log("connected, subscribed " + Tags.Length + " tags");
                    _lastR = "";   // changed-from-nothing: each fresh connection re-declares the recipe

                while (!_kill)
                {
                    // THE RATE (user 2026-10-12, restored by demand: "It
                    // should come in 2 hz as the intended speed"):
                    // cycle_s IS THE HERTZ - the user's conf said 2 meaning
                    // 2 Hz all along, and the code read it as seconds.
                    // One iteration = polls + receive + the W-word + the
                    // console line, paced to 1000/cycle_s ms (2 Hz = 500
                    // ms). The G-polls double as the keep-alive: the
                    // speedNet server reaps silent clients after ~2 s, and
                    // a burst every iteration keeps the line alive without
                    // ever free-running (the clock anchor, bench-proven).
                    bool freshThisCycle = false;
                    bool serverClosed = false;
                    var iterStart = DateTime.Now;
                    int period = Math.Max(250, (int)(1000.0 / Math.Max(0.25, _cycleS)));
                    for (int slice = 0; slice < 1 && !_kill; slice++)
                    {
                        var sliceStart = DateTime.Now;
                        // the heartbeat: one G-poll per tag per iteration
                        for (int k = 0; k < Tags.Length; k++)
                        {
                            _ws.SendAsync(new ArraySegment<byte>(Frame(Encoding.ASCII.GetBytes("G" + Tags[k] + ";"))),
                                WebSocketMessageType.Binary, true, CancellationToken.None).Wait(2000);
                        }

                        // receive + DRAIN (2026-10-13, the backlog bug): the
                        // server pours frames continuously once subscribed;
                        // ONE message per cycle read the backlog's stale head
                        // forever - the W-word carried the subscribe
                        // handshake's ghost while the arc burned (session3/1:
                        // the same six numbers through a live 15 s weld).
                        // speednet_live.py (robot-dev, the working reference)
                        // drains the pipe every round. Now: the first message
                        // waits the period, every message after waits a short
                        // drain beat; quiet pipe or the cycle deadline ends
                        // the drain. The pipe empties every cycle, the W-word
                        // carries NOW, and the pace law holds (the drain never
                        // outspends the iteration - the W-word keeps its Hz).
                        int cycleDeadline = Environment.TickCount + period;
                        if (awaiting == null)
                        {
                            awaiting = _ws.ReceiveAsync(new ArraySegment<byte>(buf), CancellationToken.None);
                        }
                        if (awaiting.Wait(period))
                        {
                            while (!_kill)
                            {
                                var res = awaiting.Result;
                                awaiting = null;
                                if (res.MessageType == WebSocketMessageType.Close)
                                {
                                    Log("server closed - reconnect");
                                    serverClosed = true;
                                    break;
                                }
                                if (res.Count > 0 && (HarvestMessage(buf, res.Count) & 1) != 0)
                                {
                                    freshThisCycle = true;
                                }
                                if (Environment.TickCount - cycleDeadline >= 0) break;
                                awaiting = _ws.ReceiveAsync(new ArraySegment<byte>(buf), CancellationToken.None);
                                if (!awaiting.Wait(25)) break;   // the drain beat: quiet pipe = drained
                            }
                        }   // the receive+drain ends (a slice's harvest)

                        // THE CLOCK ANCHOR (bench 2026-10-12): the poll
                        // answers arrive instantly - without an anchor the
                        // loop free-runs at poll-answer speed. Poll, listen,
                        // fill the iteration to its period.
                        int msLeft = period - (int)((DateTime.Now - sliceStart).TotalMilliseconds);
                        if (msLeft > 20) Thread.Sleep(msLeft);
                    }   // the paced iteration ends: polls + listen + fill,
                        // the keep-alive never silent, the stream never free
                    if (serverClosed) break;
                    if (freshThisCycle) starved = 0; else starved++;

                    // the W-word: one per cycle, the latest of each tag, verbatim
                    if (_last.Count > 0)
                    {
                        var sb = new StringBuilder("W");
                        for (int k = 0; k < 5; k++)
                        {
                            double v;
                            sb.Append(",").Append(_last.TryGetValue(Tags[k], out v) ? F6(v) : "-");
                        }
                        SendStream(sb.ToString());
                    }

                    // the error channel (701: sentinel when idle, wakes on a fault)
                    double err;
                    bool errLive = _last.TryGetValue(701, out err) && Math.Abs(err) < Sentinel;
                    if (errLive != _errOn)
                    {
                        _errOn = errLive;
                        SendWord(errLive ? ("werr " + F6(err)) : "werr clear");
                    }

                    // THE R-WORD - the recipe witness (2026-10-13 handover §1):
                    // WHAT WAS PROGRAMMED beside WHAT RAN. Six slow tags
                    // (synergy/job/programmed I/V/corrections) - NOT per-line
                    // data (user: "I do NOT want to list out all data for
                    // each line"); the werr precedent's machinery: ONE event
                    // word when the world changes. Fires once right after
                    // connect (changed-from-nothing) and again whenever a
                    // pendant hand turns anything - even mid-wall.
                    // THE TRACEABILITY HEARTBEAT (user 2026-10-13: "I want it
                    // IN every file for traceability"): the logger iterates
                    // files (stop->start: a,b,c...) while the watcher stays
                    // connected - a once-per-connect R would leave later
                    // files witnessless. So the R ALSO re-declares itself on
                    // a timer (r_heartbeat_s, default 10) - unchanged values,
                    // an ordinary witness repetition, near-top of every file
                    // longer than the period. The user's word: "I do not care
                    // if it is at top either." Field order (declared):
                    // R,<synergy 199>,<job 44>,<Iprog 13>,<Vprog 16>,
                    // <arclen 103>,<dyn 104> - values verbatim, the socket
                    // publishes display floats.
                    double syn, job, ipg, vpg, arcC, dynC;
                    if (_last.TryGetValue(199, out syn) && _last.TryGetValue(44, out job) &&
                        _last.TryGetValue(13, out ipg) && _last.TryGetValue(16, out vpg) &&
                        _last.TryGetValue(103, out arcC) && _last.TryGetValue(104, out dynC))
                    {
                        string r = "R," + F6(syn) + "," + F6(job) + "," + F6(ipg) + "," +
                                   F6(vpg) + "," + F6(arcC) + "," + F6(dynC);
                        if (r != _lastR || Environment.TickCount - _lastRSentTick >= (int)(_rHeartbeatS * 1000))
                        {
                            _lastR = r;
                            _lastRSentTick = Environment.TickCount;
                            SendWord(r);
                        }
                    }

                    // the console line (the display set verbatim - frozen
                    // between arcs exactly as the screen shows; never an arc witness)
                    double vv, ii, wf, kw, en;
                    SetStatus(string.Format(CultureInfo.InvariantCulture,
                        "{0}  V {1}  I {2}  WFS {3}  kW {4}  E {5}  err {6}",
                        _ip,
                        _last.TryGetValue(155, out vv) ? F6(vv) : "-",
                        _last.TryGetValue(154, out ii) ? F6(ii) : "-",
                        _last.TryGetValue(156, out wf) ? F6(wf) : "-",
                        _last.TryGetValue(170, out kw) ? F6(kw) : "-",
                        _last.TryGetValue(171, out en) ? F6(en) : "-",
                        errLive ? F6(err) : "-"));

                    if (starved >= 3)
                    {
                        Log("zombie: 3 cycles without values - reconnect");
                        break;
                    }
                    // no Thread.Sleep: the slices already paced this cycle
                    // (the old sleep left the line silent past the server's
                    // ~2 s reaper - the reaped-connection bug, bench 2026-10-12)
                }
            }
            catch (Exception ex)
            {
                // the FULL truth: the aggregate hides the inner exception -
                // "One or more errors occurred" told us nothing at the bench.
                var sbx = new StringBuilder("loop exception: ");
                sbx.Append(ex.Message);
                if (ex is AggregateException && ex.InnerException != null)
                {
                    sbx.Append(" | inner: ").Append(ex.InnerException.Message);
                    sbx.Append(" @ ").Append(ex.InnerException.StackTrace != null ? ex.InnerException.StackTrace : "?");
                }
                Log(sbx.ToString());
            }
            try { if (_ws != null) ((IDisposable)_ws).Dispose(); } catch { }
            _ws = null;
            awaiting = null;
            if (_kill) break;
            SetStatus("reconnecting in 5s...");
            Thread.Sleep(5000);   // the watcher watches: reconnect forever
        }
    }

    // one WebSocket message: ACK the server's request frames (the F
    // flow-control), harvest the tag values into _last. Returns bit0
    // set when fresh values landed. (Extracted from the loop body for
    // the drain, 2026-10-13 - the drain calls it once per message.)
    private int HarvestMessage(byte[] buf, int count)
    {
        int r = 0;
        var frames = ParseFrames(buf, count);
        foreach (var pl in frames)
        {
            // the F-handshake: the server's request frames get their answer
            if (pl.Length > 1 && (char)pl[0] == 'F' && NoEqualsIn(pl))
            {
                string rid = RidOf(pl);
                if (rid.Length > 0)
                {
                    try
                    {
                        _ws.SendAsync(new ArraySegment<byte>(Frame(Encoding.ASCII.GetBytes("F" + rid + "=;"))),
                            WebSocketMessageType.Binary, true, CancellationToken.None).Wait(2000);
                    }
                    catch { }
                }
            }
            var vals = ParseValues(pl);
            if (vals.Count > 0)
            {
                foreach (var kv in vals)
                {
                    if (Array.IndexOf(Tags, kv.Key) < 0) continue;
                    _last[kv.Key] = kv.Value;
                    r |= 1;
                }
            }
        }
        return r;
    }

    private static bool NoEqualsIn(byte[] pl)
    {
        int lim = Math.Min(pl.Length, 6);
        for (int i = 1; i < lim; i++) if ((char)pl[i] == '=') return false;
        return true;
    }

    private static string RidOf(byte[] pl)
    {
        var sb = new StringBuilder();
        for (int i = 1; i < pl.Length; i++)
        {
            char c = (char)pl[i];
            if (c == ',' || c == ';') break;
            if (c < '0' || c > '9') return "";
            sb.Append(c);
        }
        return sb.ToString();
    }
}
