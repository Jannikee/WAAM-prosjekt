// streams - secondary window showing EVERY field of the stream as a
// two-column table, auto-discovered from the data (however many the
// stream carries). The table header row is CHROME ONLY: left cell empty,
// right cell the cog (\u2699; red \u2715 while config is open). EVERY
// stream field is an ordinary data row - name label left (from the
// conf), value right as a big number (long text shrinks to fit, empty
// shows --). NO field is special-cased: the first field may look like a
// timestamp+word today, but it is data like any other - it could be a
// thermocouple or a loadcell from anywhere. The cog toggles an
// exclusive config panel with one name text field per stream field;
// names + PRESENTATION SCALES persist in streams.conf (one line per
// field, positional; a line is "name" or "name|scale" - the DISPLAY
// multiplies by the scale, e.g. v|0.01 shows 13.95 instead of 1395;
// THE LOG IS ALWAYS RAW - scales are presentation only, declared by
// the user in the conf, never hard-coded; unnamed fields show f<k>).
// Follows the NEWEST .csv under the logger exe folder (parent of its own
// folder) - per-layer files picked up automatically. The LAST stream
// sample of the last row is shown; values update at the 200 ms poll.
// Lonely script: reads flushed files only, never touches the logger.
// Single instance - a second launch exits silently (port 5560).
// Built in place by the build.cmd beside this file (in-box csc, C# 5).

using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Windows.Forms;
using Microsoft.VisualBasic.FileIO;

namespace streams
{
    internal class ValueCell : Panel
    {
        public string Value = "--";
        public float BaseSize = 30f;
        public Color TextColor = Color.Black;

        public ValueCell()
        {
            DoubleBuffered = true;
            ResizeRedraw = true;
            BackColor = Color.White;
        }

        public void Set(string text)
        {
            if (string.IsNullOrEmpty(text)) text = "--";
            if (Value == text) return;
            Value = text;
            Invalidate();
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            Rectangle r = ClientRectangle;
            Rectangle tr = new Rectangle(r.Left + Padding.Left, r.Top + Padding.Top,
                r.Width - Padding.Horizontal, r.Height - Padding.Vertical);
            if (tr.Width < 8 || tr.Height < 8) return;
            string text = Value;
            float size = BaseSize;
            Font f = new Font("Consolas", size, FontStyle.Bold);
            while (size > 10f && TextRenderer.MeasureText(text, f).Width > tr.Width)
            {
                f.Dispose();
                size -= 3f;
                f = new Font("Consolas", size, FontStyle.Bold);
            }
            Size sz = TextRenderer.MeasureText(text, f);
            TextRenderer.DrawText(e.Graphics, text, f,
                new Rectangle(tr.Right - sz.Width, tr.Top + (tr.Height - sz.Height) / 2, sz.Width, sz.Height),
                TextColor);
            f.Dispose();
        }
    }

    internal class MainForm : Form
    {
        private const int PollMs = 200;
        private readonly Timer _timer = new Timer();
        private readonly Panel _list = new Panel();
        private readonly Label _footer = new Label();
        private readonly Panel _hdr = new Panel();
        private readonly Label _cog = new Label();
        private readonly Panel _cfg = new Panel();
        private readonly List<ValueCell> _num = new List<ValueCell>();
        private readonly List<Label> _nameLbl = new List<Label>();
        private readonly List<TextBox> _cfgBox = new List<TextBox>();
        private readonly List<string> _names = new List<string>();
        private bool _cfgOpen = false;
        private string _confPath;
        private string[] _fields = null;
        private int _built = -1;
        private string _path;
        private long _size = -1;
        private DateTime _mtime = DateTime.MinValue;
        private int _samples;

        public MainForm()
        {
            Text = "streams";
            ClientSize = new Size(560, 400);
            MinimumSize = new Size(420, 300);
            BackColor = Color.White;
            _list.Dock = DockStyle.Fill;
            _list.AutoScroll = true;
            _list.BackColor = Color.White;
            _footer.Dock = DockStyle.Bottom;
            _footer.Height = 22;
            _footer.Font = new Font("Consolas", 8.5f);
            _footer.ForeColor = Color.FromArgb(120, 120, 120);
            _footer.TextAlign = ContentAlignment.MiddleLeft;
            _footer.Padding = new Padding(12, 3, 0, 0);
            _footer.Text = "waiting for a csv ...";
            _hdr.Dock = DockStyle.Top;
            _hdr.Height = 30;
            _hdr.BackColor = Color.White;
            _cog.Text = "\u2699";
            _cog.Font = new Font("Segoe UI", 14f);
            _cog.ForeColor = Color.FromArgb(130, 130, 130);
            _cog.AutoSize = false;
            _cog.Size = new Size(36, 30);
            _cog.TextAlign = ContentAlignment.MiddleCenter;
            _cog.Location = new Point(_hdr.Width - 46, 0);
            _cog.Cursor = Cursors.Hand;
            _cog.Click += delegate { ToggleCfg(); };
            _cog.MouseEnter += delegate { _cog.ForeColor = _cfgOpen ? Color.FromArgb(170, 20, 20) : Color.FromArgb(17, 17, 17); };
            _cog.MouseLeave += delegate { _cog.ForeColor = _cfgOpen ? Color.FromArgb(200, 40, 40) : Color.FromArgb(130, 130, 130); };
            _hdr.Controls.Add(_cog);
            _hdr.Resize += delegate { _cog.Location = new Point(_hdr.Width - 46, 0); };
            _cfg.Dock = DockStyle.Bottom;
            _cfg.Height = 0;
            _cfg.Visible = false;
            _cfg.BackColor = Color.White;
            _cfg.AutoScroll = true;
            Controls.Add(_list);
            Controls.Add(_cfg);
            Controls.Add(_footer);
            Controls.Add(_hdr);
            _confPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "streams.conf");
            LoadNames();
            _timer.Interval = PollMs;
            _timer.Tick += delegate { Poll(); };
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
            try
            {
                using (var parser = new TextFieldParser(path, System.Text.Encoding.UTF8))
                {
                    parser.HasFieldsEnclosedInQuotes = true;
                    parser.TextFieldType = FieldType.Delimited;
                    parser.SetDelimiters(",");
                    string[] header = parser.ReadFields();
                    if (header == null) return;
                    int si = Array.IndexOf(header, "stream");
                    if (si < 0) return;
                    _samples = 0;
                    string lastCell = null;
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
                        _samples++;
                        if (row.Length > si && !string.IsNullOrEmpty(row[si])) lastCell = row[si];
                    }
                    if (lastCell == null)
                    {
                        _fields = null;
                        return;
                    }
                    string seg = null;
                    foreach (string s in lastCell.Split(';'))
                    {
                        if (!string.IsNullOrWhiteSpace(s)) seg = s.Trim();
                    }
                    _fields = seg == null ? null : seg.Split(',');
                }
            }
            catch (Exception)
            {
            }
        }

        private void Poll()
        {
            string newest = FindNewest();
            if (!string.Equals(newest, _path, StringComparison.OrdinalIgnoreCase))
            {
                _path = newest;
                _size = -1;
                _mtime = DateTime.MinValue;
                _fields = null;
            }
            if (_path != null && File.Exists(_path))
            {
                var fi = new FileInfo(_path);
                if (fi.Length != _size || fi.LastWriteTimeUtc != _mtime)
                {
                    _size = fi.Length;
                    _mtime = fi.LastWriteTimeUtc;
                    ParseFile(_path);
                }
            }
            string f = _path == null
                ? "waiting for a csv ..."
                : Path.GetFileName(_path) + "  |  " + _samples + " rows";
            if (_fields == null)
            {
                f += "  |  no stream samples yet";
                if (_built != 0) Rebuild(0);
            }
            else
            {
                f += "  |  names: streams.conf";
                if (_fields.Length != _built) Rebuild(_fields.Length);
                for (int i = 0; i < _fields.Length; i++)
                {
                    string t = _fields[i];
                    double sc = ScaleFor(i);
                    if (sc != 1.0)
                    {
                        double num;
                        if (double.TryParse(t, NumberStyles.Float, CultureInfo.InvariantCulture, out num))
                        {
                            int dec = 0;
                            double d = sc;
                            while (d < 0.999999 && dec < 6) { d *= 10.0; dec++; }
                            t = (num * sc).ToString("F" + dec, CultureInfo.InvariantCulture);
                        }
                    }
                    _num[i].Set(t);
                }
            }
            _footer.Text = f;
        }

        private void Rebuild(int n)
        {
            _list.Controls.Clear();
            _num.Clear();
            _nameLbl.Clear();
            _cfg.Controls.Clear();
            _cfgBox.Clear();
            _built = n;
            int nameW = 140;
            using (Font nf = new Font("Consolas", 11f))
            {
                for (int i = 0; i < n; i++)
                {
                    int w = TextRenderer.MeasureText(NameFor(i), nf).Width + 12;
                    if (w > nameW) nameW = w;
                }
            }
            for (int i = n - 1; i >= 0; i--)
            {
                int idx = i;
                Panel line = new Panel();
                line.Dock = DockStyle.Top;
                line.Height = 32;
                line.BackColor = Color.White;
                Label idxLbl = new Label();
                idxLbl.Text = "f" + (idx + 1);
                idxLbl.Font = new Font("Consolas", 9f);
                idxLbl.ForeColor = Color.FromArgb(120, 120, 120);
                idxLbl.Size = new Size(40, 20);
                idxLbl.Location = new Point(12, 7);
                TextBox cfgTb = new TextBox();
                cfgTb.Font = new Font("Consolas", 11f);
                cfgTb.BorderStyle = BorderStyle.FixedSingle;
                cfgTb.Size = new Size(220, 24);
                cfgTb.Location = new Point(56, 4);
                cfgTb.Text = idx < _names.Count ? _names[idx] : "";
                cfgTb.TextChanged += delegate
                {
                    while (_names.Count <= idx) _names.Add("");
                    _names[idx] = cfgTb.Text;
                    SaveNames();
                };
                line.Controls.Add(cfgTb);
                line.Controls.Add(idxLbl);
                _cfg.Controls.Add(line);
                _cfgBox.Insert(0, cfgTb);
            }
            for (int i = n - 1; i >= 0; i--)
            {
                int idx = i;
                Panel row = new Panel();
                row.Dock = DockStyle.Top;
                row.Height = 64;
                row.BackColor = Color.White;
                ValueCell cell = new ValueCell();
                cell.Dock = DockStyle.Fill;
                cell.Padding = new Padding(nameW + 20, 4, 14, 4);
                Label nameLbl = new Label();
                nameLbl.Font = new Font("Consolas", 11f);
                nameLbl.ForeColor = Color.FromArgb(17, 17, 17);
                nameLbl.AutoSize = false;
                nameLbl.Size = new Size(nameW, 24);
                nameLbl.Location = new Point(12, 20);
                nameLbl.Text = NameFor(idx);
                row.Controls.Add(nameLbl);
                row.Controls.Add(cell);
                _list.Controls.Add(row);
                _num.Insert(0, cell);
                _nameLbl.Insert(0, nameLbl);
            }
            FitWindow(n);
        }

        private void FitWindow(int n)
        {
            int widest = 0;
            using (Font mf = new Font("Consolas", 30f, FontStyle.Bold))
            {
                for (int i = 0; i < n; i++)
                {
                    string t = (_fields != null && i < _fields.Length && _fields[i] != "") ? _fields[i] : "--";
                    int w = TextRenderer.MeasureText(t, mf).Width;
                    if (w > widest) widest = w;
                }
            }
            int nameW = 140;
            using (Font nf = new Font("Consolas", 11f))
            {
                for (int i = 0; i < n; i++)
                {
                    int w = TextRenderer.MeasureText(NameFor(i), nf).Width + 12;
                    if (w > nameW) nameW = w;
                }
            }
            int chromeW = Width - ClientSize.Width;
            int chromeH = Height - ClientSize.Height;
            int wantW = 12 + nameW + 20 + widest + 14 + 12 + chromeW;
            int wantH = 30 + n * 64 + 22 + chromeH;
            Rectangle wa = Screen.GetWorkingArea(this);
            if (wantW > wa.Width - 20) wantW = wa.Width - 20;
            if (wantH > wa.Height - 20) wantH = wa.Height - 20;
            if (wantW < MinimumSize.Width) wantW = MinimumSize.Width;
            if (wantH < MinimumSize.Height) wantH = MinimumSize.Height;
            if (wantW != Width || wantH != Height) Size = new Size(wantW, wantH);
        }

        private void ToggleCfg()
        {
            _cfgOpen = !_cfgOpen;
            if (_cfgOpen)
            {
                _list.Visible = false;
                _footer.Visible = false;
                _cfg.Visible = true;
                _cfg.Dock = DockStyle.Fill;
                _cog.Text = "\u2715";
                _cog.ForeColor = Color.FromArgb(200, 40, 40);
            }
            else
            {
                _cfg.Visible = false;
                _cfg.Dock = DockStyle.Bottom;
                _cfg.Height = 0;
                _list.Visible = true;
                _footer.Visible = true;
                for (int i = 0; i < _nameLbl.Count; i++) _nameLbl[i].Text = NameFor(i);
                _cog.Text = "\u2699";
                _cog.ForeColor = Color.FromArgb(130, 130, 130);
            }
        }

        private string NameFor(int idx)
        {
            if (idx < _names.Count && !string.IsNullOrEmpty(_names[idx]))
                return _names[idx].Split('|')[0];
            return "f" + (idx + 1);
        }

        private double ScaleFor(int idx)
        {
            if (idx < _names.Count)
            {
                string[] parts = _names[idx].Split('|');
                double sc;
                if (parts.Length > 1 && double.TryParse(parts[1], NumberStyles.Float, CultureInfo.InvariantCulture, out sc) && sc > 0)
                    return sc;
            }
            return 1.0;
        }

        private void LoadNames()
        {
            try
            {
                if (File.Exists(_confPath))
                {
                    _names.AddRange(File.ReadAllLines(_confPath));
                    return;
                }
            }
            catch (Exception)
            {
            }
            _names.AddRange(new string[] { "word", "x", "y", "z", "nx", "ny", "nz", "v|0.01", "i|0.1", "wfs|0.01" });
            SaveNames();
        }

        private void SaveNames()
        {
            try
            {
                File.WriteAllLines(_confPath, _names.ToArray());
            }
            catch (Exception)
            {
            }
        }
    }

    internal static class Program
    {
        private const int LockPort = 5560;

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
