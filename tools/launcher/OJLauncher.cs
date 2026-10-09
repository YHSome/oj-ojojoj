// ============================================================================
//  OJ 一键启动器（WinForms，单文件）
//
//  设计原则：**绝不去启动浏览器**。
//  旧版本会用 5 种方式轮番尝试唤起浏览器，在某些机器上会反复拉起浏览器进程
//  导致系统卡死；现在改为：启动判题机 + 中控台 → 地址显示在窗口里 + 自动复制
//  到剪贴板，用户自己粘贴到浏览器打开。
//
//  双击：启动判题机 → 启动中控台 → 把中控台地址复制到剪贴板
//  命令行（结果写 logs\launcher.log）：
//      OJ中控台.exe --start             启动并退出
//      OJ中控台.exe --stop              全部停止
//      OJ中控台.exe --status            0=都在跑，1=有没跑的
//      OJ中控台.exe --urls              打印两个地址（便于脚本取用）
//
//  编译： python tools\build_launcher.py   （用系统自带 csc.exe，零依赖）
// ============================================================================
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net.Sockets;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;

static class OjEnv
{
    public static string Root;
    public static string Python;
    public static string LogFile;
    public static int ConsolePort = 8090;
    public static string ConsoleUrl { get { return "http://127.0.0.1:" + ConsolePort + "/"; } }
    public static string FrontUrl = "https://yhsome.github.io/oj-ojojoj/";

    static OjEnv()
    {
        string dir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        if (File.Exists(Path.Combine(dir, "tools", "oj_service.py"))) Root = dir;
        else if (File.Exists(@"D:\OJ\tools\oj_service.py")) Root = @"D:\OJ";
        else Root = dir;

        string bundled = @"C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe";
        if (File.Exists(bundled)) Python = bundled; else Python = "python";

        LogFile = Path.Combine(Root, "logs", "launcher.log");
        try { Directory.CreateDirectory(Path.Combine(Root, "logs")); } catch { }
    }

    public static Action<string> OnLog;

    public static void Log(string msg)
    {
        string line = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "  " + msg;
        try { File.AppendAllText(LogFile, line + Environment.NewLine, Encoding.UTF8); } catch { }
        if (OnLog != null) OnLog(line);
    }

    public static bool PortOpen(int port, int timeoutMs)
    {
        try
        {
            using (var c = new TcpClient())
            {
                var ar = c.BeginConnect("127.0.0.1", port, null, null);
                if (!ar.AsyncWaitHandle.WaitOne(timeoutMs)) return false;
                c.EndConnect(ar);
                return true;
            }
        }
        catch { return false; }
    }

    public static string RunPython(string scriptArgs, int timeoutMs)
    {
        var psi = new ProcessStartInfo();
        psi.FileName = Python;
        psi.Arguments = scriptArgs;
        psi.WorkingDirectory = Root;
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;
        psi.RedirectStandardOutput = true;
        psi.RedirectStandardError = true;
        psi.StandardOutputEncoding = Encoding.UTF8;
        psi.StandardErrorEncoding = Encoding.UTF8;
        psi.EnvironmentVariables["PYTHONUTF8"] = "1";
        psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
        try
        {
            var p = Process.Start(psi);
            string outp = p.StandardOutput.ReadToEnd() + p.StandardError.ReadToEnd();
            if (!p.WaitForExit(timeoutMs)) { try { p.Kill(); } catch { } return outp + "\n(超时)"; }
            return outp;
        }
        catch (Exception e) { return "启动失败: " + e.Message; }
    }

    public static Process StartDetached(string scriptArgs)
    {
        var psi = new ProcessStartInfo();
        psi.FileName = Python;
        psi.Arguments = scriptArgs;
        psi.WorkingDirectory = Root;
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;
        psi.EnvironmentVariables["PYTHONUTF8"] = "1";
        psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
        return Process.Start(psi);
    }

    public static int JudgePid()
    {
        try
        {
            string lockPath = Path.Combine(Root, "data", "state", "daemon.lock");
            if (!File.Exists(lockPath)) return 0;
            string txt = File.ReadAllText(lockPath, Encoding.UTF8);
            var m = Regex.Match(txt, "\"pid\"\\s*:\\s*(\\d+)");
            if (!m.Success) return 0;
            int pid = int.Parse(m.Groups[1].Value);
            try { var p = Process.GetProcessById(pid); return p.HasExited ? 0 : pid; }
            catch { return 0; }
        }
        catch { return 0; }
    }

    public static bool JudgeRunning() { return JudgePid() > 0; }

    /// <summary>只复制，不打开任何程序。</summary>
    public static bool Copy(string text)
    {
        try { Clipboard.SetText(text); Log("已复制到剪贴板: " + text); return true; }
        catch (Exception e) { Log("复制失败: " + e.Message); return false; }
    }

    public static bool EnsureConsole()
    {
        if (PortOpen(ConsolePort, 400)) { Log("中控台已在运行（:" + ConsolePort + "）"); return true; }
        Log("启动中控台服务 python tools/console.py --port " + ConsolePort + " …");
        StartDetached("tools\\console.py --port " + ConsolePort);
        for (int i = 0; i < 60; i++)
        {
            Thread.Sleep(300);
            if (PortOpen(ConsolePort, 300)) { Log("中控台已就绪: " + ConsoleUrl); return true; }
        }
        Log("中控台启动超时（20 秒内端口未监听）");
        return false;
    }

    public static bool StartJudge()
    {
        if (JudgeRunning()) { Log("判题机已在运行（pid=" + JudgePid() + "）"); return true; }
        Log("启动判题机 …");
        string outp = RunPython("tools\\oj_service.py start", 90000);
        foreach (string line in outp.Split('\n'))
            if (line.Trim().Length > 0) Log("  | " + line.TrimEnd());
        return JudgeRunning();
    }

    public static bool StopAll()
    {
        bool ok = true;
        Log("停止判题机 …");
        RunPython("tools\\oj_service.py stop", 60000);
        ok = !JudgeRunning();
        int pid = PidByPort(ConsolePort);
        if (pid > 0)
        {
            Log("停止中控台（pid=" + pid + "）");
            try { Process.GetProcessById(pid).Kill(); } catch { }
            Thread.Sleep(600);
        }
        if (PortOpen(ConsolePort, 300)) { Log("中控台仍在监听，请手动检查"); ok = false; }
        return ok;
    }

    public static int PidByPort(int port)
    {
        try
        {
            var psi = new ProcessStartInfo("netstat", "-ano -p tcp");
            psi.UseShellExecute = false; psi.CreateNoWindow = true;
            psi.RedirectStandardOutput = true; psi.StandardOutputEncoding = Encoding.ASCII;
            var p = Process.Start(psi);
            string txt = p.StandardOutput.ReadToEnd();
            p.WaitForExit(10000);
            foreach (string line in txt.Split('\n'))
            {
                if (line.IndexOf(":" + port, StringComparison.Ordinal) < 0) continue;
                if (line.IndexOf("LISTENING", StringComparison.OrdinalIgnoreCase) < 0) continue;
                var parts = line.Split(new char[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
                if (parts.Length >= 5)
                {
                    int pid;
                    if (int.TryParse(parts[parts.Length - 1], out pid)) return pid;
                }
            }
            return 0;
        }
        catch { return 0; }
    }
}

class MainForm : Form
{
    Label lJudge, lConsole, lTip;
    TextBox box, tbConsole, tbFront;
    Button bStart, bStop, bCopyConsole, bCopyFront, bProbe;
    System.Windows.Forms.Timer timer;

    public MainForm()
    {
        Text = "OJ 判题机 · 一键启动（不自动开浏览器）";
        ClientSize = new Size(600, 470);
        StartPosition = FormStartPosition.CenterScreen;
        Font = new Font("Microsoft YaHei UI", 9F);

        var title = new Label();
        title.Text = "一键启动：判题机 + 后端中控台";
        title.Font = new Font(Font.FontFamily, 13F, FontStyle.Bold);
        title.AutoSize = true; title.Location = new Point(16, 12);
        Controls.Add(title);

        lJudge = new Label(); lJudge.AutoSize = true; lJudge.Location = new Point(18, 48);
        lConsole = new Label(); lConsole.AutoSize = true; lConsole.Location = new Point(18, 72);
        lTip = new Label(); lTip.AutoSize = true; lTip.Location = new Point(18, 98);
        lTip.ForeColor = Color.DimGray;
        lTip.Text = "地址会自动复制到剪贴板 —— 自己粘贴到浏览器打开（本程序不启动任何浏览器）";
        Controls.Add(lJudge); Controls.Add(lConsole); Controls.Add(lTip);

        // ---- 两个地址（只读文本框，点一下即全选，方便手动复制） ----
        var l1 = new Label(); l1.Text = "中控台地址"; l1.AutoSize = true; l1.Location = new Point(18, 126);
        Controls.Add(l1);
        tbConsole = new TextBox();
        tbConsole.Location = new Point(100, 122); tbConsole.Size = new Size(482, 24);
        tbConsole.ReadOnly = true; tbConsole.Text = OjEnv.ConsoleUrl;
        tbConsole.Click += (s, e) => tbConsole.SelectAll();
        Controls.Add(tbConsole);

        var l2 = new Label(); l2.Text = "考生端地址"; l2.AutoSize = true; l2.Location = new Point(18, 156);
        Controls.Add(l2);
        tbFront = new TextBox();
        tbFront.Location = new Point(100, 152); tbFront.Size = new Size(482, 24);
        tbFront.ReadOnly = true; tbFront.Text = OjEnv.FrontUrl;
        tbFront.Click += (s, e) => tbFront.SelectAll();
        Controls.Add(tbFront);

        // ---- 按钮 ----
        bStart = new Button(); bStart.Text = "▶  一键启动"; bStart.Location = new Point(18, 188);
        bStart.Size = new Size(126, 34); bStart.Click += (s, e) => DoStart();
        bStop = new Button(); bStop.Text = "■  全部停止"; bStop.Location = new Point(152, 188);
        bStop.Size = new Size(126, 34); bStop.Click += (s, e) => DoStop();

        bCopyConsole = new Button(); bCopyConsole.Text = "复制中控台地址";
        bCopyConsole.Location = new Point(286, 188); bCopyConsole.Size = new Size(140, 34);
        bCopyConsole.Click += (s, e) => { OjEnv.Copy(OjEnv.ConsoleUrl); Flash("中控台地址已复制"); };

        bCopyFront = new Button(); bCopyFront.Text = "复制考生端地址";
        bCopyFront.Location = new Point(434, 188); bCopyFront.Size = new Size(140, 34);
        bCopyFront.Click += (s, e) => { OjEnv.Copy(OjEnv.FrontUrl); Flash("考生端地址已复制"); };

        bProbe = new Button(); bProbe.Text = "刷新状态";
        bProbe.Location = new Point(18, 230); bProbe.Size = new Size(110, 26);
        bProbe.Click += (s, e) => Refresh2();
        Controls.Add(bStart); Controls.Add(bStop); Controls.Add(bCopyConsole);
        Controls.Add(bCopyFront); Controls.Add(bProbe);

        box = new TextBox();
        box.Multiline = true; box.ScrollBars = ScrollBars.Vertical;
        box.Location = new Point(18, 264); box.Size = new Size(564, 192);
        box.ReadOnly = true; box.BackColor = Color.FromArgb(20, 22, 28);
        box.ForeColor = Color.Gainsboro; box.Font = new Font("Consolas", 9F);
        Controls.Add(box);

        OjEnv.OnLog = (line) =>
        {
            if (box.IsDisposed) return;
            try
            {
                box.AppendText(line + "\r\n");
                box.SelectionStart = box.TextLength; box.ScrollToCaret();
            }
            catch { }
        };

        timer = new System.Windows.Forms.Timer(); timer.Interval = 2000;
        timer.Tick += (s, e) => Refresh2();
        timer.Start();

        Load += (s, e) =>
        {
            Refresh2();
            if (OjEnv.JudgeRunning() && OjEnv.PortOpen(OjEnv.ConsolePort, 300))
            {
                OjEnv.Log("已在运行中；已为你复制中控台地址，去浏览器粘贴即可");
                OjEnv.Copy(OjEnv.ConsoleUrl);
                Flash("中控台地址已复制，粘到浏览器打开");
            }
            else DoStart();
        };
    }

    void Flash(string msg)
    {
        lTip.Text = msg + "（自己粘贴到浏览器打开）";
        lTip.ForeColor = Color.SeaGreen;
    }

    void Refresh2()
    {
        bool j = OjEnv.JudgeRunning(), c = OjEnv.PortOpen(OjEnv.ConsolePort, 250);
        int pid = OjEnv.JudgePid();
        lJudge.Text = "判题机：" + (j ? "运行中（pid=" + pid + "）" : "已停止");
        lJudge.ForeColor = j ? Color.SeaGreen : Color.Firebrick;
        lConsole.Text = "中控台：" + (c ? "运行中（" + OjEnv.ConsoleUrl + "）" : "已停止");
        lConsole.ForeColor = c ? Color.SeaGreen : Color.Firebrick;
    }

    void DoStart()
    {
        bStart.Enabled = false;
        ThreadPool.QueueUserWorkItem(_ =>
        {
            try
            {
                OjEnv.StartJudge();
                bool cok = OjEnv.EnsureConsole();
                try
                {
                    BeginInvoke(new Action(() =>
                    {
                        Refresh2();
                        if (cok)
                        {
                            OjEnv.Copy(OjEnv.ConsoleUrl);
                            Flash("启动完成，中控台地址已复制");
                        }
                        else Flash("中控台没起来，请看下面日志");
                    }));
                }
                catch { }
            }
            finally
            {
                try { BeginInvoke(new Action(() => { bStart.Enabled = true; })); } catch { }
            }
        });
    }

    void DoStop()
    {
        bStop.Enabled = false;
        ThreadPool.QueueUserWorkItem(_ =>
        {
            try { OjEnv.StopAll(); }
            finally
            {
                try { BeginInvoke(new Action(() => { bStop.Enabled = true; Refresh2(); })); }
                catch { }
            }
        });
    }
}

static class Program
{
    [STAThread]
    static int Main(string[] args)
    {
        bool headless = false, doStop = false, doStatus = false, doUrls = false;
        foreach (string a in args)
        {
            string s = a.ToLowerInvariant();
            if (s == "--start") headless = true;
            else if (s == "--stop") { headless = true; doStop = true; }
            else if (s == "--status") { headless = true; doStatus = true; }
            else if (s == "--urls") { headless = true; doUrls = true; }
        }

        if (headless)
        {
            OjEnv.Log("=== 命令行模式: " + string.Join(" ", args) + " ===");
            if (doUrls)
            {
                Console.WriteLine(OjEnv.ConsoleUrl);
                Console.WriteLine(OjEnv.FrontUrl);
                OjEnv.Log("中控台: " + OjEnv.ConsoleUrl);
                OjEnv.Log("考生端: " + OjEnv.FrontUrl);
                return 0;
            }
            if (doStatus)
            {
                bool j = OjEnv.JudgeRunning(), c = OjEnv.PortOpen(OjEnv.ConsolePort, 300);
                OjEnv.Log("判题机: " + (j ? "运行中 pid=" + OjEnv.JudgePid() : "已停止"));
                OjEnv.Log("中控台: " + (c ? "运行中 " + OjEnv.ConsoleUrl : "已停止"));
                return (j && c) ? 0 : 1;
            }
            if (doStop) return OjEnv.StopAll() ? 0 : 1;
            bool okJ = OjEnv.StartJudge();
            bool okC = OjEnv.EnsureConsole();
            if (okC) OjEnv.Copy(OjEnv.ConsoleUrl);
            OjEnv.Log("结果: 判题机=" + (okJ ? "OK" : "失败") + " 中控台=" + (okC ? "OK" : "失败")
                      + "（中控台地址已复制到剪贴板，请粘贴到浏览器）");
            return (okJ && okC) ? 0 : 1;
        }

        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new MainForm());
        return 0;
    }
}
