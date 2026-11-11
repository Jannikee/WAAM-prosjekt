// img_cap1.cs - ONE PHOTO, ONE PROCESS. The trigger runs the show.
//
// The logger's rule owns the when, the how many, the pace; this tool is a
// stateless instrument: start -> init camera -> first frame -> decode ->
// img_<M>.png + one img.log row -> exit. No window on screen (a hidden
// pump form - the WinRT frame events need a pumped STA), no mutex, no kill
// bat, no timer, no state: the burst is the rule's job now.
//
//   the rule:   on_stop|0|img_cap.exe|1|8|1|5|0
//               = cond | val | act | enabled | runs 8 | inf | refire 5s | delay 0
//               -> 8 photos, 5 s apart, first immediately (user spec 2026-10-10)
//
// Data dir: conf data_dir > LOGGER_LOG_DIR (the logger hands every fired
// script its session folder) > the launch directory.
// NEVER OVERWRITE: <prefix>_<M>.png - count from 1, first free number.
// <prefix>.log: timestamp,imagename - one row per photo, append-only.
// THE CAMERA IS THE NAME (user 2026-10-11: "if I create ir_cap1.exe I
// should also have ir_cap1.conf... the filenames should have ir1_1.png
// 1_2 1_3... so log files would have the name ir1.log"): exe and conf
// pair at the same name level, and the number rides the files - copy
// img_cap.exe to img_cap1.exe, give img_cap1.conf its own
// camera_index, and its photos are img1_1.png, img1_2.png... in
// img1.log. No registry, no limits - a named copy is a new camera.
// Failure = honest: a missing photo + a trail line (<exe>.log beside
// the exe); the user owns the conflicts (Teams grabbing the camera mid-burst).
//
// Build: build_img1.cmd (in-box csc, zero installs).

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

internal class ImgCapForm : Form
{
    private int _cameraIndex = 0;
    private int _frameW = 0;      // 0 0 = ALWAYS the highest available (the
        private int _frameH = 0;      // generic rule; conf values = the override
    private string _dataDir = "";

    private string _exeBase = "img_cap1";   // the exe's own name = the camera's identity
    private string _prefix = "img1";       // _cap stripped: img_cap1 -> img1 (the file prefix)

    private string _base;
    private int _m;                    // the photo number: <prefix>_<M>.png
    private MediaCapture _mc;
    private MediaFrameReader _reader;
    private bool _done;
    private readonly object _logLock = new object();

    private static int Main()
    {
        Application.EnableVisualStyles();
        var f = new ImgCapForm();
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

    public ImgCapForm()
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
                    "# " + _exeBase + ".conf - the one-shot photo tool's knobs.",
                    "# The rule owns the cadence (runs/refire/delay); this is only",
                    "# the camera + the resolution + where the photos go.",
                    "# THE NAME IS THE CAMERA: this conf pairs with " + _exeBase + ".exe;",
                    "# (its photos are " + _prefix + "_<M>.png, its trail " + _prefix + ".log).",
                    "# AFTER 1 FOLLOWS 2: copy " + _exeBase + ".exe to " + NextName(_exeBase) + ".exe",
                    "# for another camera - its conf is created on its first run;",
                    "# give it its own camera_index.",
                    "camera_index=" + _cameraIndex,
                    "# frame_width/frame_height: 0 0 (the default) = ALWAYS the",
                    "# highest resolution available (the generic rule); explicit",
                    "# values = the declared override (the log lists every",
                    "# format the camera refuses).",
                    "frame_width=0",
                    "frame_height=0",
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
                else if (k == "frame_width" && int.TryParse(v, out n) && n >= 0) _frameW = n;
                else if (k == "frame_height" && int.TryParse(v, out n) && n >= 0) _frameH = n;
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

            // THE GENERIC RULE (user 2026-10-10): ALWAYS the highest resolution
            // available - unless the conf declares the override (values > 0).
            bool setOk = false;
            if (_frameW > 0 && _frameH > 0)
            {
                foreach (var f in src.SupportedFormats)
                {
                    if (f.VideoFormat.Width == (uint)_frameW && f.VideoFormat.Height == (uint)_frameH)
                    { WinRT.WaitAction(src.SetFormatAsync(f), 15000); setOk = true; break; }
                }
            }
            else
            {
                MediaFrameFormat best = null; uint bestArea = 0;
                foreach (var f in src.SupportedFormats)
                {
                    uint area = f.VideoFormat.Width * f.VideoFormat.Height;
                    if (area > bestArea) { bestArea = area; best = f; }
                }
                if (best != null)
                { WinRT.WaitAction(src.SetFormatAsync(best), 15000); setOk = true; _frameW = (int)best.VideoFormat.Width; _frameH = (int)best.VideoFormat.Height; }
            }
            if (!setOk)
            {
                foreach (var f in src.SupportedFormats)
                    Log("format: " + f.VideoFormat.Width + "x" + f.VideoFormat.Height + " " + f.Subtype);
                Log("no " + _frameW + "x" + _frameH + " - see log formats");
                return;
            }
            Log("format " + _frameW + "x" + _frameH + " set");

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

    private void OnFrameArrived(MediaFrameReader sender, MediaFrameArrivedEventArgs args)
    {
        if (_done) return;
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

            // THE SUBTYPE DECIDES THE DECODE: webcams here are NV12-only;
            // YUY2 stays for the packed devices. BT.601 coefficients.
            bool nv12 = sbt.BitmapPixelFormat == BitmapPixelFormat.Nv12;
            var pd1 = lb.GetPlaneDescription(nv12 ? 1 : 0);
            int w = pd0.Width, h = pd0.Height, stride = pd0.Stride;
            var bmp = new System.Drawing.Bitmap(w, h, System.Drawing.Imaging.PixelFormat.Format24bppRgb);
            var bd = bmp.LockBits(new System.Drawing.Rectangle(0, 0, w, h),
                System.Drawing.Imaging.ImageLockMode.WriteOnly,
                System.Drawing.Imaging.PixelFormat.Format24bppRgb);
            unsafe
            {
                for (int y = 0; y < h; y++)
                {
                    byte* dst = (byte*)bd.Scan0 + y * bd.Stride;
                    if (nv12)
                    {
                        if (pd0.StartIndex + y * stride + w > (int)cap) break;
                        if (pd1.StartIndex + (y >> 1) * pd1.Stride + w > (int)cap) break;
                        byte* srcY = (byte*)data + pd0.StartIndex + y * stride;
                        byte* srcUV = (byte*)data + pd1.StartIndex + (y >> 1) * pd1.Stride;
                        for (int x = 0; x < w; x++)
                        {
                            int Y = srcY[x];
                            int u = srcUV[(x >> 1) * 2] - 128, v = srcUV[(x >> 1) * 2 + 1] - 128;
                            int r = Y + (int)(1.402f * v), g = Y - (int)(0.344136f * u + 0.714136f * v), b = Y + (int)(1.772f * u);
                            dst[x * 3] = (byte)(b < 0 ? 0 : b > 255 ? 255 : b);
                            dst[x * 3 + 1] = (byte)(g < 0 ? 0 : g > 255 ? 255 : g);
                            dst[x * 3 + 2] = (byte)(r < 0 ? 0 : r > 255 ? 255 : r);
                        }
                    }
                    else
                    {
                        if (pd0.StartIndex + y * stride + w * 2 > (int)cap) break;   // bound to capacity
                        byte* src = (byte*)data + pd0.StartIndex + y * stride;
                        for (int x = 0; x < w; x += 2)
                        {
                            int o = x * 2;
                            int y0 = src[o], u = src[o + 1] - 128, y1 = src[o + 2], v = src[o + 3] - 128;
                            int r0 = y0 + (int)(1.402f * v), g0 = y0 - (int)(0.344136f * u + 0.714136f * v), b0 = y0 + (int)(1.772f * u);
                            int r1 = y1 + (int)(1.402f * v), g1 = y1 - (int)(0.344136f * u + 0.714136f * v), b1 = y1 + (int)(1.772f * u);
                            dst[x * 3] = (byte)(b0 < 0 ? 0 : b0 > 255 ? 255 : b0);
                            dst[x * 3 + 1] = (byte)(g0 < 0 ? 0 : g0 > 255 ? 255 : g0);
                            dst[x * 3 + 2] = (byte)(r0 < 0 ? 0 : r0 > 255 ? 255 : r0);
                            if (x + 1 < w)
                            {
                                dst[(x + 1) * 3] = (byte)(b1 < 0 ? 0 : b1 > 255 ? 255 : b1);
                                dst[(x + 1) * 3 + 1] = (byte)(g1 < 0 ? 0 : g1 > 255 ? 255 : g1);
                                dst[(x + 1) * 3 + 2] = (byte)(r1 < 0 ? 0 : r1 > 255 ? 255 : r1);
                            }
                        }
                    }
                }
            }
            bmp.UnlockBits(bd);

            // save + log + exit - ONE photo, then the process dies
            string imgName = _prefix + "_" + (_m + 1) + ".png";
            Directory.CreateDirectory(_base);
            bmp.Save(Path.Combine(_base, imgName), System.Drawing.Imaging.ImageFormat.Png);
            string lp = Path.Combine(_base, _prefix + ".log");
            if (!File.Exists(lp)) File.AppendAllText(lp, "timestamp,imagename" + Environment.NewLine);
            File.AppendAllText(lp,
                DateTime.Now.ToString("yyyy-MM-ddTHH:mm:ss.fff", CultureInfo.InvariantCulture) + "," + imgName + Environment.NewLine);
            _done = true;
            Log("photo saved: " + imgName + " (" + w + "x" + h + ")");
            bmp.Dispose();
            BeginInvoke((MethodInvoker)delegate { Close(); });
        }
        finally
        {
            try { bb.Dispose(); } catch { }
            try { lb.Dispose(); } catch { }
            try { sbt.Dispose(); } catch { }
            try { frame.Dispose(); } catch { }
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
