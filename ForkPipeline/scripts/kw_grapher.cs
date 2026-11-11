// kw_grapher - live kW readout + graph from the fork logger's CSV.
// Built with the in-box .NET Framework compiler (build.cmd) - zero installs.
// Launched by the trigger rule:  if on_start run kw_grapher.exe
// (single instance - a second launch exits silently, so per-layer
// on_start fires are harmless.)
// It follows the NEWEST .csv under the logger exe folder (the parent of
// its own folder) - per-layer files are picked up automatically and the
// plot resets when the file switches. U and I come from the S-word fields
// (S,x,y,z,nx,ny,nz,v,i,wfs) in the stream column - the raw Fronius bus
// words. Verify the word->unit scale once against the pendant WELDER
// tab, then edit the scales below.

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Windows.Forms;
using Microsoft.VisualBasic.FileIO;

namespace kw_grapher
{
    internal class KwChart : Panel
    {
        public const int MaxPoints = 300;
        public List<double> Data = new List<double>();
        public double Avg = double.NaN;
        public double Mean = double.NaN;

        public KwChart()
        {
            DoubleBuffered = true;
            ResizeRedraw = true;
            BackColor = Color.White;
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            if (Data.Count < 2) return;
            int n = Math.Min(Data.Count, MaxPoints);
            double min = double.MaxValue, max = double.MinValue;
            for (int i = Data.Count - n; i < Data.Count; i++)
            {
                if (Data[i] < min) min = Data[i];
                if (Data[i] > max) max = Data[i];
            }
            if (max - min < 0.000001) { max += 1.0; min -= 1.0; }
            int pad = 6;
            float w = ClientSize.Width - 2 * pad;
            float h = ClientSize.Height - 2 * pad;
            if (w <= 0 || h <= 0) return;
            using (var capFont = new Font("Segoe UI", 8f))
            using (var valFont = new Font("Segoe UI", 9f, FontStyle.Bold))
            {
                string maxText = max.ToString("F2", CultureInfo.InvariantCulture);
                string minText = min.ToString("F2", CultureInfo.InvariantCulture);
                Size capSz = TextRenderer.MeasureText("max ", capFont);
                Size valSz = TextRenderer.MeasureText(maxText, valFont);
                TextRenderer.DrawText(e.Graphics, "max ", capFont, new Point(pad + 2, pad - 1), Color.FromArgb(102, 102, 102));
                TextRenderer.DrawText(e.Graphics, maxText, valFont, new Point(pad + 2 + capSz.Width, pad - 2), Color.FromArgb(46, 164, 79));
                int by = ClientSize.Height - pad - valSz.Height;
                TextRenderer.DrawText(e.Graphics, "min ", capFont, new Point(pad + 2, by), Color.FromArgb(102, 102, 102));
                TextRenderer.DrawText(e.Graphics, minText, valFont, new Point(pad + 2 + capSz.Width, by - 1), Color.FromArgb(46, 164, 79));
                // avg = time-average of instantaneous kW (matches the Fronius
                // display means); mean = meanV x meanI (the naive product of
                // the pendant means) - both over the WHOLE session file.
                if (!double.IsNaN(Avg) && !double.IsNaN(Mean))
                {
                    float yAvg = pad + h - (float)((Avg - min) / (max - min)) * h;
                    float yMean = pad + h - (float)((Mean - min) / (max - min)) * h;
                    if (yMean > yAvg - 14 && yMean < yAvg + 14) yMean = yAvg + 14;
                    if (yAvg < pad) yAvg = pad;
                    if (yAvg > pad + h - valSz.Height) yAvg = pad + h - valSz.Height;
                    if (yMean < pad) yMean = pad;
                    if (yMean > pad + h - valSz.Height) yMean = pad + h - valSz.Height;
                    TextRenderer.DrawText(e.Graphics, "avg ", capFont, new Point(pad + 2, (int)yAvg), Color.FromArgb(102, 102, 102));
                    TextRenderer.DrawText(e.Graphics, Avg.ToString("F2", CultureInfo.InvariantCulture), valFont, new Point(pad + 2 + capSz.Width, (int)yAvg - 1), Color.FromArgb(46, 164, 79));
                    TextRenderer.DrawText(e.Graphics, "mean ", capFont, new Point(pad + 2, (int)yMean), Color.FromArgb(102, 102, 102));
                    TextRenderer.DrawText(e.Graphics, Mean.ToString("F2", CultureInfo.InvariantCulture), valFont, new Point(pad + 2 + capSz.Width, (int)yMean - 1), Color.FromArgb(46, 164, 79));
                }
            }
            float step = w / (MaxPoints - 1);
            using (var pen = new Pen(Color.FromArgb(9, 105, 218), 2f))
            {
                bool down = false;
                float lx = 0, ly = 0, x = pad + w - (n - 1) * step;
                for (int i = Data.Count - n; i < Data.Count; i++)
                {
                    float y = pad + h - (float)((Data[i] - min) / (max - min)) * h;
                    if (down) e.Graphics.DrawLine(pen, lx, ly, x, y);
                    lx = x; ly = y; down = true; x += step;
                }
            }
        }
    }

    internal class MainForm : Form
    {
        // SCALES VERIFIED 2026-10-05 on cell 2 (pendant vs logged words):
        // W#20150 voltage = raw x 0.01 (1395 -> 13.95 V),
        // W#20170 current = raw x 0.1 (928 -> 92.8 A),
        // W#20190 wfs = raw x 0.01 (378 -> 3.78 m/min).
        private const double VScale = 0.01;
        private const double IScale = 0.1;
        private const double KwDiv = 1000.0;
        private const int PollMs = 200;
        private const int VField = 7;
        private const int IField = 8;

        private readonly Label _val = new Label();
        private readonly Label _unit = new Label();
        private readonly Label _status = new Label();
        private readonly KwChart _chart = new KwChart();
        private readonly System.Windows.Forms.Timer _timer = new System.Windows.Forms.Timer();
        private List<double> _data = new List<double>();
        private double _sumV, _sumI, _sumP;
        private long _cnt;
        private string _path;
        private long _size = -1;
        private DateTime _mtime = DateTime.MinValue;

        public MainForm()
        {
            Text = "kw_grapher";
            ClientSize = new Size(560, 400);
            MinimumSize = new Size(420, 280);
            BackColor = Color.White;
            _val.Font = new Font("Consolas", 44f, FontStyle.Bold);
            _val.Text = "--";
            _val.ForeColor = Color.FromArgb(17, 17, 17);
            _val.Dock = DockStyle.Top;
            _val.Height = 84;
            _val.TextAlign = ContentAlignment.MiddleCenter;
            _unit.Font = new Font("Segoe UI", 12f);
            _unit.Text = "kW";
            _unit.ForeColor = Color.FromArgb(102, 102, 102);
            _unit.Dock = DockStyle.Top;
            _unit.Height = 24;
            _unit.TextAlign = ContentAlignment.MiddleCenter;
            _status.Font = new Font("Consolas", 9f);
            _status.Text = "waiting for a csv ...";
            _status.ForeColor = Color.FromArgb(102, 102, 102);
            _status.Dock = DockStyle.Top;
            _status.Height = 18;
            _status.TextAlign = ContentAlignment.MiddleLeft;
            _status.Padding = new Padding(12, 2, 0, 0);
            _chart.Dock = DockStyle.Fill;
            Controls.Add(_chart);
            Controls.Add(_status);
            Controls.Add(_unit);
            Controls.Add(_val);
            _timer.Interval = PollMs;
            _timer.Tick += OnTick;
            _timer.Start();
        }

        private static string Root()
        {
            return Path.GetDirectoryName(Path.GetDirectoryName(AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar)));
        }

        private static string FindNewest()
        {
            try
            {
                string root = Root();
                if (root == null || !Directory.Exists(root)) return null;
                string best = null;
                DateTime bestMt = DateTime.MinValue;
                    foreach (string p in Directory.EnumerateFiles(root, "*.csv", System.IO.SearchOption.AllDirectories))
                {
                    try
                    {
                        DateTime mt = File.GetLastWriteTimeUtc(p);
                        if (mt > bestMt)
                        {
                            bestMt = mt;
                            best = p;
                        }
                    }
                    catch (Exception) { }
                }
                return best;
            }
            catch (Exception)
            {
                return null;
            }
        }

        private void ParseFile(string path)
        {
            var vals = new List<double>();
            _sumV = 0; _sumI = 0; _sumP = 0; _cnt = 0;
            try
            {
                using (var parser = new TextFieldParser(path, System.Text.Encoding.UTF8))
                {
                    parser.HasFieldsEnclosedInQuotes = true;
                    parser.TextFieldType = FieldType.Delimited;
                    parser.SetDelimiters(",");
                    string[] header = parser.ReadFields();
                    if (header == null) { _data = vals; return; }
                    int si = Array.IndexOf(header, "stream");
                    if (si < 0) { _data = vals; return; }
                    while (!parser.EndOfData)
                    {
                        string[] row;
                        try
                        {
                            row = parser.ReadFields();
                        }
                        catch (MalformedLineException)
                        {
                            break;
                        }
                        if (row == null) break;
                        if (row.Length <= si || string.IsNullOrEmpty(row[si])) continue;
                        foreach (string sample in row[si].Split(';'))
                        {
                            string[] p = sample.Split(',');
                            if (p.Length <= IField || !p[0].EndsWith(" S")) continue;
                            double v, i;
                            if (!double.TryParse(p[VField], NumberStyles.Float, CultureInfo.InvariantCulture, out v)) continue;
                            if (!double.TryParse(p[IField], NumberStyles.Float, CultureInfo.InvariantCulture, out i)) continue;
                            double kw = v * VScale * i * IScale / KwDiv;
                            vals.Add(kw);
                            _sumV += v * VScale;
                            _sumI += i * IScale;
                            _sumP += kw;
                            _cnt++;
                        }
                    }
                }
            }
            catch (Exception)
            {
            }
            _data = vals;
        }

        private void OnTick(object sender, EventArgs e)
        {
            string newest = FindNewest();
            if (!string.Equals(newest, _path, StringComparison.OrdinalIgnoreCase))
            {
                _path = newest;
                _size = -1;
                _mtime = DateTime.MinValue;
                _data = new List<double>();
            }
            if (_path != null && File.Exists(_path))
            {
                var fi = new FileInfo(_path);
                if (fi.Length != _size || fi.LastWriteTimeUtc != _mtime)
                {
                    _size = fi.Length;
                    _mtime = fi.LastWriteTimeUtc;
                    ParseFile(_path);
                    _val.Text = _data.Count > 0 ? _data[_data.Count - 1].ToString("F2", CultureInfo.InvariantCulture) : "--";
                    _status.Text = Path.GetFileName(_path) + "  |  " + _data.Count + " samples";
                    _chart.Data = _data;
                    if (_cnt > 0)
                    {
                        _chart.Avg = _sumP / _cnt;
                        _chart.Mean = (_sumV / _cnt) * (_sumI / _cnt) / KwDiv;
                    }
                    else
                    {
                        _chart.Avg = double.NaN;
                        _chart.Mean = double.NaN;
                    }
                    _chart.Invalidate();
                }
            }
        }
    }

    internal static class Program
    {
        private const int LockPort = 5559;

        [STAThread]
        private static void Main()
        {
            TcpListener lck = null;
            try
            {
                lck = new TcpListener(IPAddress.Loopback, LockPort);
                lck.Start();
            }
            catch (SocketException)
            {
                return;
            }
            Application.EnableVisualStyles();
            Application.Run(new MainForm());
            GC.KeepAlive(lck);
        }
    }
}
