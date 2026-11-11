// Bell - the C# port of bell.py (fork companion tool, zero installs).
// Shows a 400x400 px bell centered on the screen; any key or mouse button
// closes it. Same drawing as the python original: cream background, gold
// bell with dark outline - knob, smooth dome, rim, clapper.
// PLUS A RING: a real bell ringing synthesized in memory - three decaying
// strikes over ~3 seconds, 830 Hz + 2.4x/3.9x/0.5x partials, normalized
// loud, no sound file - plays on the speakers when the window opens;
// closing the window silences it.
// Built in place by the build.cmd beside this file (in-box csc, C# 5).
using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Media;
using System.Windows.Forms;

class BellForm : Form
{
    SoundPlayer player;

    public BellForm()
    {
        Text = "Bell - press any key to close";
        FormBorderStyle = FormBorderStyle.FixedSingle;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.Manual;
        ClientSize = new Size(400, 400);
        int x = (Screen.PrimaryScreen.Bounds.Width - 400) / 2;
        int y = (Screen.PrimaryScreen.Bounds.Height - 400) / 2;
        Location = new Point(x, y);
        KeyPreview = true;
        DoubleBuffered = true;
        BackColor = Color.FromArgb(0xf7, 0xf3, 0xea);
        KeyDown += delegate { Close(); };
        MouseDown += delegate { Close(); };
        Paint += OnPaint;
        Shown += delegate { Ring(); };
        FormClosed += delegate { if (player != null) player.Stop(); };
    }

    void Ring()
    {
        int rate = 44100;
        double f = 830.0;
        double strike = 1.4;
        double gap = 0.8;
        int strikes = 3;
        int n = (int)(rate * (gap * (strikes - 1) + strike));
        float[] mix = new float[n];
        for (int k = 0; k < strikes; k++)
        {
            int off = (int)(rate * gap * k);
            int ns = (int)(rate * strike);
            for (int i = 0; i < ns && off + i < n; i++)
            {
                double t = (double)i / rate;
                double env = Math.Exp(-t * 2.2);
                double v = 0.45 * Math.Sin(2.0 * Math.PI * f * t)
                         + 0.22 * Math.Sin(2.0 * Math.PI * f * 2.4 * t) * Math.Exp(-t * 6.0)
                         + 0.12 * Math.Sin(2.0 * Math.PI * f * 3.9 * t) * Math.Exp(-t * 9.0)
                         + 0.08 * Math.Sin(2.0 * Math.PI * f * 0.5 * t) * Math.Exp(-t * 2.0);
                mix[off + i] += (float)(v * env);
            }
        }
        float peak = 0.0000001f;
        for (int i = 0; i < n; i++)
        {
            float a = mix[i] < 0 ? -mix[i] : mix[i];
            if (a > peak) peak = a;
        }
        double gain = 28000.0 / (double)peak;
        short[] s = new short[n];
        for (int i = 0; i < n; i++)
        {
            double v = mix[i] * gain;
            if (v > 28000.0) v = 28000.0;
            if (v < -28000.0) v = -28000.0;
            s[i] = (short)v;
        }
        byte[] wav = new byte[44 + n * 2];
        Array.Copy(System.Text.Encoding.ASCII.GetBytes("RIFF"), 0, wav, 0, 4);
        WriteInt(wav, 4, 36 + n * 2);
        Array.Copy(System.Text.Encoding.ASCII.GetBytes("WAVE"), 0, wav, 8, 4);
        Array.Copy(System.Text.Encoding.ASCII.GetBytes("fmt "), 0, wav, 12, 4);
        WriteInt(wav, 16, 16);
        WriteShort(wav, 20, 1);
        WriteShort(wav, 22, 1);
        WriteInt(wav, 24, rate);
        WriteInt(wav, 28, rate * 2);
        WriteShort(wav, 32, 2);
        WriteShort(wav, 34, 16);
        Array.Copy(System.Text.Encoding.ASCII.GetBytes("data"), 0, wav, 36, 4);
        WriteInt(wav, 40, n * 2);
        Buffer.BlockCopy(s, 0, wav, 44, n * 2);
        MemoryStream ms = new MemoryStream(wav);
        player = new SoundPlayer(ms);
        player.Play();
    }

    static void WriteInt(byte[] b, int off, int v)
    {
        b[off] = (byte)v;
        b[off + 1] = (byte)(v >> 8);
        b[off + 2] = (byte)(v >> 16);
        b[off + 3] = (byte)(v >> 24);
    }

    static void WriteShort(byte[] b, int off, int v)
    {
        b[off] = (byte)v;
        b[off + 1] = (byte)(v >> 8);
    }

    void OnPaint(object sender, PaintEventArgs e)
    {
        Graphics g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        Color gold = Color.FromArgb(0xe6, 0xb4, 0x22);
        Color dark = Color.FromArgb(0x7a, 0x62, 0x1a);
        Color clap = Color.FromArgb(0xc8, 0xa0, 0x17);
        Brush bg = new SolidBrush(gold);
        Brush cb = new SolidBrush(clap);
        Pen pen = new Pen(dark, 3f);
        PointF[] pts = new PointF[]
        {
            new PointF(200, 58), new PointF(238, 96), new PointF(246, 150),
            new PointF(262, 214), new PointF(286, 272), new PointF(114, 272),
            new PointF(138, 214), new PointF(154, 150), new PointF(162, 96)
        };
        GraphicsPath path = new GraphicsPath();
        path.AddClosedCurve(pts, 0.5f);
        g.FillPath(bg, path);
        g.DrawPath(pen, path);
        g.FillEllipse(bg, 186, 36, 28, 28);
        g.DrawEllipse(pen, 186, 36, 28, 28);
        g.FillEllipse(bg, 96, 262, 208, 44);
        g.DrawEllipse(pen, 96, 262, 208, 44);
        g.FillEllipse(cb, 182, 304, 36, 36);
        g.DrawEllipse(pen, 182, 304, 36, 36);
        path.Dispose();
        pen.Dispose();
        bg.Dispose();
        cb.Dispose();
    }

    [STAThread]
    static void Main()
    {
        Application.EnableVisualStyles();
        Application.Run(new BellForm());
    }
}
