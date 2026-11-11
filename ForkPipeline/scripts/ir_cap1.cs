// ir_cap1.cs - ONE THERMAL PHOTO, ONE PROCESS. The trigger runs the show.
//
// The logger's rule owns the when, the how many, the pace; this tool is a
// stateless instrument (the thermal sibling of img_cap): start -> init the
// P2 Pro -> first frame -> decode the radiometric payload -> the rendered
// grid ir_<M>.png + one ir.log row (with the hottest-spot temp) -> exit.
//
//   the rule:   on_stop|0|ir_cap.exe|1|8|1|5|0   (8 photos, 5 s apart)
//
// The decode (the proven one): 256x384 YUY2; rows 192..383 = the Y16
// radiometric payload, 16-bit little-endian, temp = raw/64 - 273.2 per
// pixel. The render: the min-max stretched grayscale grid + the red box at
// the hottest spot - exactly the image the old resident tool produced.
// NO SIGNAL LOGIC (user 2026-10-10: "same as speed logging. not our task
// as of now") - this tool photographs and logs, nothing more.
//
// Data dir: conf data_dir > LOGGER_LOG_DIR > the launch directory.
// NEVER OVERWRITE: <prefix>_<M>.png - count from 1, first free number.
// <prefix>.log: timestamp,imagename,temp_C - append-only, invariant culture.
// THE CAMERA IS THE NAME (user 2026-10-11, the 3-thermal-cam comparison
// bench): exe and conf pair at the same name level - ir_cap1.exe gets
// ir_cap1.conf (its own camera_index = its own camera), and the number
// rides the files: ir1_1.png, ir1_2.png... in ir1.log. Copy the exe
// under a new name = a new camera; no registry, no limits.
//
// Build: build_ir1.cmd (in-box csc, zero installs).

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using Windows.Foundation;
using Windows.Graphics.Imaging;
using Windows.Media.Capture;
using Windows.Media.Capture.Frames;

internal class IrCapForm : Form
{
    private const int W = 256, H = 192;                 // radiometric grid
    private const double SatC = 52685.0 / 64.0 - 273.2; // ~550 C sensor cap

    private int _cameraIndex = 1;                      // the P2 Pro (group 1)
    private string _dataDir = "";

    private string _exeBase = "ir_cap1";   // the exe's own name = the camera's identity
    private string _prefix = "ir1";       // _cap stripped: ir_cap1 -> ir1 (the file prefix)

    private string _base;
    private int _m;                    // the photo number: <prefix>_<M>.png
    private MediaCapture _mc;
    private MediaFrameReader _reader;
    private bool _done;
    private readonly object _logLock = new object();

    private static int Main()
    {
        Application.EnableVisualStyles();
        var f = new IrCapForm();
        f.ResolveIdentity();
        f.LoadConf();
        f.ResolveDir();
        f.CountSlot();
        f.InitCamera();
        if (f._reader == null) { f.Log("no reader - exiting"); return 1; }
        var t = new System.Windows.Forms.Timer();
        t.Interval = 12000;   // no frame in 12 s = the honest failure
        t.Tick += delegate { if (!f._done) { f.Log("timeout: no frame in 12s - exiting"); Environment.Exit(1); } };
        t.Start();
        Application.Run(f);
        return f._done ? 0 : 1;
    }

    public IrCapForm()
    {
        ShowInTaskbar = false;
        WindowState = FormWindowState.Minimized;
        FormBorderStyle = FormBorderStyle.FixedToolWindow;
    }

    // never visible - but a real pumped form (the WinRT events demand it)
    protected override void SetVisibleCore(bool value)
    {
        if (!IsHandleCreated) CreateHandle();
        base.SetVisibleCore(false);
    }

    private string ExeDir()
    {
        return Path.GetDirectoryName(System.Diagnostics.Process.GetCurrentProcess().MainModule.FileName);
    }

    // THE CAMERA IS THE NAME: the exe's own file name is the identity -
    // ir_cap1.exe pairs with ir_cap1.conf and writes ir1_<M>.png + ir1.log.
    // "_cap" strips away (the tool suffix); everything before and after is
    // the prefix. A name without _cap keeps its whole self as the prefix.
    private void ResolveIdentity()
    {
        try
        {
            string b = Path.GetFileNameWithoutExtension(System.Diagnostics.Process.GetCurrentProcess().MainModule.FileName);
            if (!string.IsNullOrEmpty(b)) _exeBase = b;
        }
        catch { }
        int cap = _exeBase.ToLowerInvariant().IndexOf("_cap");
        _prefix = cap >= 0 ? _exeBase.Substring(0, cap) + _exeBase.Substring(cap + 4) : _exeBase;
        Log("identity: " + _exeBase + " -> " + _prefix + "_<M>.png in " + _prefix + ".log");
    }


    // the next exe name (ir_cap1 -> ir_cap2): AFTER 1 FOLLOWS 2 (user
    // 2026-10-11) - the convention the conf hints at, computed from
    // the tool's own name.
    private static string NextName(string name)
    {
        int d = name.Length;
        while (d > 0 && name[d - 1] >= '0' && name[d - 1] <= '9') d--;
        return d < name.Length
            ? name.Substring(0, d) + (long.Parse(name.Substring(d)) + 1).ToString(CultureInfo.InvariantCulture)
            : name + "2";
    }

    private void Log(string s)
    {
        lock (_logLock)
        {
            try
            {
                File.AppendAllText(Path.Combine(ExeDir(), _exeBase + ".log"),
                    DateTime.Now.ToString("HH:mm:ss.fff") + " " + s + Environment.NewLine);
            }
            catch { }
        }
    }

    private void LoadConf()
    {
        try
        {
            string p = Path.Combine(ExeDir(), _exeBase + ".conf");
            if (!File.Exists(p))
            {
                File.WriteAllLines(p, new string[]
                {
                    "# " + _exeBase + ".conf - the one-shot thermal photo tool's knobs.",
                    "# The rule owns the cadence (runs/refire/delay); this is only",
                    "# the camera + where the photos go. No signal logic (not our task).",
                    "# THE NAME IS THE CAMERA: this conf pairs with " + _exeBase + ".exe;",
                    "# (its photos are " + _prefix + "_<M>.png, its trail " + _prefix + ".log).",
                    "# AFTER 1 FOLLOWS 2: copy " + _exeBase + ".exe to " + NextName(_exeBase) + ".exe",
                    "# for another camera - its conf is created on its first run;",
                    "# give it its own camera_index.",
                    "camera_index=" + _cameraIndex,
                    "# data_dir: where the photos go. Empty = LOGGER_LOG_DIR (the",
                    "# logger's session folder) > the launch directory.",
                    "data_dir=" + _dataDir
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
                if (k == "camera_index" && int.TryParse(v, out n)) _cameraIndex = n;
                else if (k == "data_dir") _dataDir = v;
            }
        }
        catch { }
    }

    private void ResolveDir()
    {
        if (!string.IsNullOrEmpty(_dataDir)) { _base = _dataDir; return; }
        string loggerDir = Environment.GetEnvironmentVariable("LOGGER_LOG_DIR");
        if (!string.IsNullOrEmpty(loggerDir)) { _base = loggerDir; return; }
        _base = Environment.CurrentDirectory;
        try { Directory.CreateDirectory(_base); } catch { }
    }

    private void CountSlot()
    {
        // NEVER OVERWRITE: count from 1, first free number (the user law)
        _m = 0;
        while (File.Exists(Path.Combine(_base, _prefix + "_" + (_m + 1) + ".png"))) _m++;
        Log("photo slot: " + _prefix + "_" + (_m + 1) + ".png in " + _base);
    }

    // ---------------- camera: the frame server (WinRT, UI thread) ----------------
    private void InitCamera()
    {
        try
        {
            var groups = WinRT.Wait(MediaFrameSourceGroup.FindAllAsync(), 20000);
            var colorGroups = new List<MediaFrameSourceGroup>();
            foreach (var g in groups)
            {
                if (!g.Id.StartsWith("\\\\?\\USB")) continue;
                foreach (var si in g.SourceInfos)
                    if (si.SourceKind == MediaFrameSourceKind.Color) { colorGroups.Add(g); break; }
            }
            if (_cameraIndex >= colorGroups.Count)
            {
                Log("camera_index " + _cameraIndex + " but only " + colorGroups.Count + " camera(s)");
                return;
            }
            string nm = "?";
            foreach (var si in colorGroups[_cameraIndex].SourceInfos)
                if (si.SourceKind == MediaFrameSourceKind.Color && si.DeviceInformation != null) nm = si.DeviceInformation.Name;
            Log("camera " + _cameraIndex + ": " + nm);

            _mc = new MediaCapture();
            var s = new MediaCaptureInitializationSettings();
            s.SourceGroup = colorGroups[_cameraIndex];
            s.SharingMode = MediaCaptureSharingMode.ExclusiveControl;   // the format set must be real
            s.MemoryPreference = MediaCaptureMemoryPreference.Cpu;
            WinRT.WaitAction(_mc.InitializeAsync(s), 25000);
            MediaFrameSource src = null;
            foreach (var kv in _mc.FrameSources)
                if (kv.Value.Info.SourceKind == MediaFrameSourceKind.Color) src = kv.Value;
            if (src == null) { Log("no color frame source"); return; }

            // the P2 Pro's thermal format: 256x384 YUY2 (the payload rides rows 192-383)
            bool setOk = false;
            foreach (var f in src.SupportedFormats)
            {
                if (f.VideoFormat.Width == 256 && f.VideoFormat.Height == 384)
                { WinRT.WaitAction(src.SetFormatAsync(f), 15000); setOk = true; break; }
            }
            if (!setOk)
            {
                foreach (var f in src.SupportedFormats)
                    Log("format: " + f.VideoFormat.Width + "x" + f.VideoFormat.Height + " " + f.Subtype);
                Log("no 256x384 - see log formats");
                return;
            }
            Log("format 256x384 set");

            _reader = WinRT.Wait(_mc.CreateFrameReaderAsync(src), 15000);
            _reader.FrameArrived += new TypedEventHandler<MediaFrameReader, MediaFrameArrivedEventArgs>(OnFrameArrived);
            var status = WinRT.Wait(_reader.StartAsync(), 15000);
            Log("reader started: " + status);
        }
        catch (Exception ex)
        {
            Log("init failed: " + ex.Message);
            try { if (_mc != null) ((IDisposable)_mc).Dispose(); } catch { }
            _mc = null;
        }
    }

    // rows 192..383 = the Y16 payload. Decode, render, save, log, exit.
    private void OnFrameArrived(MediaFrameReader sender, MediaFrameArrivedEventArgs args)
    {
        if (_done) return;
        try
        {
            var frame = sender.TryAcquireLatestFrame();
            if (frame == null) return;
            var sbt = frame.VideoMediaFrame == null ? null : frame.VideoMediaFrame.SoftwareBitmap;
            if (sbt == null) { frame.Dispose(); return; }
            var lb = sbt.LockBuffer(BitmapBufferAccessMode.Read);
            var pd0 = lb.GetPlaneDescription(0);
            var bb = lb.CreateReference();
            try
            {
                var access = (WinRT.IMemoryBufferByteAccess)bb;   // RCW cast = QI
                IntPtr data; uint cap;
                access.GetBuffer(out data, out cap);

                float[] tt = new float[H * W];
                int best = 0; float bestT = float.MinValue;
                int stride = pd0.Stride;
                int y1 = Math.Min(pd0.Height, 192 + H);
                int x1 = Math.Min(W, pd0.Width);
                for (int y = 192; y < y1; y++)
                    for (int x = 0; x < x1; x++)
                    {
                        int o = pd0.StartIndex + y * stride + x * 2;
                        if (o + 1 >= (int)cap) continue;
                        float temp = ((Marshal.ReadByte(data, o) | (Marshal.ReadByte(data, o + 1) << 8)) / 64f) - 273.2f;
                        int iy = y - 192;
                        tt[iy * W + x] = temp;
                        if (temp > bestT) { bestT = temp; best = iy * W + x; }
                    }

                // the render: the min-max stretched grayscale grid + the red box
                // at the hottest spot - the same image the old resident produced
                float mn = float.MaxValue, mx = float.MinValue;
                for (int i = 0; i < tt.Length; i++) { if (tt[i] < mn) mn = tt[i]; if (tt[i] > mx) mx = tt[i]; }
                float span = Math.Max(0.01f, mx - mn);
                var bmp = new System.Drawing.Bitmap(W, H, System.Drawing.Imaging.PixelFormat.Format24bppRgb);
                var bd = bmp.LockBits(new System.Drawing.Rectangle(0, 0, W, H),
                    System.Drawing.Imaging.ImageLockMode.WriteOnly, System.Drawing.Imaging.PixelFormat.Format24bppRgb);
                unsafe
                {
                    byte* row = (byte*)bd.Scan0;
                    for (int y = 0; y < H; y++)
                    {
                        byte* p = row + y * bd.Stride;
                        for (int x = 0; x < W; x++)
                        {
                            int v = (int)(255f * (tt[y * W + x] - mn) / span);
                            if (v < 0) v = 0; if (v > 255) v = 255;
                            p[x * 3] = (byte)v; p[x * 3 + 1] = (byte)v; p[x * 3 + 2] = (byte)v;
                        }
                    }
                }
                bmp.UnlockBits(bd);
                int bx = best % W, by = best / W;
                using (var g = System.Drawing.Graphics.FromImage(bmp))
                {
                    using (var pen = new System.Drawing.Pen(System.Drawing.Color.Red, 1f))
                        g.DrawRectangle(pen, bx - 3, by - 3, 7, 7);
                    // THE MAX TEMP beside the red box (user 2026-10-10: "write
                    // max temp on the side of the red dot a bit big text") -
                    // baked into the photo product; outlined for any gray level.
                    using (var f = new System.Drawing.Font("Consolas", 16f, System.Drawing.FontStyle.Bold))
                    {
                        string txt = bestT.ToString("F1", CultureInfo.InvariantCulture) + "\u00B0C";
                        var sz = g.MeasureString(txt, f);
                        float tx = bx + 9, ty = by - 10;
                        if (tx + sz.Width > W) tx = bx - 9 - sz.Width;
                        if (ty < 0) ty = by + 4;
                        if (ty + sz.Height > H) ty = H - sz.Height - 1;
                        using (var brB = new System.Drawing.SolidBrush(System.Drawing.Color.Black))
                        {
                            g.DrawString(txt, f, brB, tx + 1.5f, ty + 1.5f);
                            g.DrawString(txt, f, brB, tx - 1.5f, ty + 1.5f);
                            g.DrawString(txt, f, brB, tx + 1.5f, ty - 1.5f);
                            g.DrawString(txt, f, brB, tx - 1.5f, ty - 1.5f);
                        }
                        using (var br = new System.Drawing.SolidBrush(System.Drawing.Color.Yellow))
                            g.DrawString(txt, f, br, tx, ty);
                    }
                }

                // save + log + exit - ONE photo, then the process dies
                string imgName = _prefix + "_" + (_m + 1) + ".png";
                Directory.CreateDirectory(_base);
                bmp.Save(Path.Combine(_base, imgName), System.Drawing.Imaging.ImageFormat.Png);
                string lp = Path.Combine(_base, _prefix + ".log");
                if (!File.Exists(lp)) File.AppendAllText(lp, "timestamp,imagename,temp_C" + Environment.NewLine);
                File.AppendAllText(lp,
                    DateTime.Now.ToString("yyyy-MM-ddTHH:mm:ss.fff", CultureInfo.InvariantCulture) + "," + imgName + ","
                    + bestT.ToString("F2", CultureInfo.InvariantCulture) + Environment.NewLine);
                _done = true;
                Log("photo saved: " + imgName + " (hottest " + bestT.ToString("F1", CultureInfo.InvariantCulture) + " C)");
                bmp.Dispose();
                BeginInvoke((MethodInvoker)delegate { Close(); });
            }
            finally
            {
                // EVERY object released, every time - SoftwareBitmap holds a
                // STRONG reference the frame's Dispose does not clear.
                try { bb.Dispose(); } catch { }
                try { lb.Dispose(); } catch { }
                try { sbt.Dispose(); } catch { }
                try { frame.Dispose(); } catch { }
            }
        }
        catch (Exception ex)
        {
            Log("frame failed: " + ex.Message);
        }
    }

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        // release the camera for the next shot in the burst
        try { if (_reader != null) { WinRT.WaitAction(_reader.StopAsync(), 5000); ((IDisposable)_reader).Dispose(); } } catch { }
        try { if (_mc != null) ((IDisposable)_mc).Dispose(); } catch { }
        base.OnFormClosed(e);
    }
}

static class WinRT
{
    public static T Wait<T>(IAsyncOperation<T> op, int ms)
    {
        var mre = new ManualResetEvent(false);
        op.Completed = new AsyncOperationCompletedHandler<T>(
            delegate(IAsyncOperation<T> o, AsyncStatus s) { mre.Set(); });
        mre.WaitOne(ms);
        return op.GetResults();
    }

    public static void WaitAction(IAsyncAction op, int ms)
    {
        var mre = new ManualResetEvent(false);
        op.Completed = new AsyncActionCompletedHandler(
            delegate(IAsyncAction o, AsyncStatus s) { mre.Set(); });
        mre.WaitOne(ms);
    }

    // IID verified vs Microsoft's doc (process-media-frames-with-
    // mediaframereader, 2026-10-09). The RCW cast does the QI.
    [ComImport, Guid("5B0D3235-4DBA-4D44-865E-8F1D0E4FD04D"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IMemoryBufferByteAccess
    {
        void GetBuffer(out IntPtr value, out uint capacity);
    }
}
