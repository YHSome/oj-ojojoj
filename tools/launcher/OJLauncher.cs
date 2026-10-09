// ============================================================================
//  OJ 一键启动器（WinForms，单文件，编译产物为真正的 .exe）
//
//  双击后：启动判题机 → 启动后端中控台 → 自动打开浏览器访问中控台。
//  也支持命令行（便于自动化/排错，结果写入 logs\launcher.log）：
//      OJ中控台.exe --start [--no-browser]   启动并退出（不开界面）
//      OJ中控台.exe --stop                   全部停止
//      OJ中控台.exe --status                 写状态后退出（0=都在跑，1=有没跑的）
//
//  编译：tools\build_launcher.cmd（用系统自带 csc.exe，不需要装任何东西）
// ============================================================================
using System;
using System.Collections.Generic;
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
        // 1) 仓库根目录：exe 所在目录优先；找不到就回退到 D:\OJ
        string dir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        if (File.Exists(Path.Combine(dir, "tools", "oj_service.py"))) Root = dir;
        else if (File.Exists(@"D:\OJ\tools\oj_service.py")) Root = @"D:\OJ";
        else Root = dir;

        // 2) Python：先用随 DSH 附带的运行时，其次 PATH 里的 python
        string bundled = @"C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe";
        if (File.Exists(bundled)) Python = bundled; else Python = "python";

        LogFile = Path.Combine(Root, "logs", "launcher.log");
        try { Directory.CreateDirectory(Path.Combine(Root, "logs")); } catch { }
    }

    public static void Log(string msg)
    {
        string line = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "  " + msg;
        try { File.AppendAllText(LogFile, line + Environment.NewLine, Encoding.UTF8); } catch { }
        if (OnLog != null) OnLog(line);
    }

    public static Action<string> OnLog;

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

    /// <summary>跑一个 python 脚本并等它结束（隐藏窗口），返回输出。</summary>
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

    /// <summary>后台常驻启动（中控台服务用），不等待退出。</summary>
    public static Process StartDetached(string scriptArgs)
    {
        var psi = new ProcessStartInfo();
        psi.FileName = Python;
        psi.Arguments = scriptArgs;
        psi.WorkingDirectory = Root;
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;
        psi.RedirectStandardOutput = false;
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

    public static void OpenUrl(string url)
    {
        OpenUrlVerbose(url);
    }

    /// <summary>浏览器进程数（用于验证"到底打开没有"）。</summary>
    static int BrowserCount()
    {
        int n = 0;
        string[] names = { "msedge", "chrome", "firefox", "brave", "opera", "iexplore", "360se", "QQBrowser" };
        foreach (string nm in names)
        {
            try { n += Process.GetProcessesByName(nm).Length; } catch { }
        }
        return n;
    }

    /// <summary>把一个 URL 交给系统打开；多种方式依次尝试，并记录每一步结果。</summary>
    public static bool OpenUrlVerbose(string url)
    {
        // ② .NET ShellExecute；③ cmd start；④ 直接叫浏览器；⑤ explorer；⑥ 注册表
        int before = BrowserCount();
        Log("试着打开 " + url + (before > 0 ? "（浏览器已在运行 " + before + " 个进程）" : "（当前没有浏览器进程）"));

        // ① .NET ShellExecute —— 标准做法，但在某些机器上会静默失败（不抛异常）
        try
        {
            Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
            if (WaitBrowser(before, 3)) { Log("  [OK] ShellExecute 打开成功"); return true; }
            Log("  [--] ShellExecute 没反应，换下一种");
        }
        catch (Exception e) { Log("  [--] ShellExecute 失败: " + e.Message); }

        // ② cmd /c start（最可靠；但 start 即使打不开也会返回 0，所以还要看浏览器进程）
        try
        {
            var psi = new ProcessStartInfo("cmd.exe", "/c start \"\" \"" + url + "\"");
            psi.UseShellExecute = false; psi.CreateNoWindow = true;
            var p = Process.Start(psi);
            p.WaitForExit(8000);
            bool seen = WaitBrowser(before, 3);
            if (p.ExitCode == 0 && (seen || before > 0))
            { Log("  [OK] cmd start 打开（退出码 0" + (seen ? "，已看到浏览器进程" : "，浏览器原本就在运行") + "）"); return true; }
            Log("  [--] cmd start 退出码 " + p.ExitCode + (seen ? "" : "，且没看到浏览器进程"));
        }
        catch (Exception e) { Log("  [--] cmd start 失败: " + e.Message); }

        // ③ 直接叫浏览器（用户可能没设默认浏览器）
        string[] edges = {
            @"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            @"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            @"C:\Program Files\Google\Chrome\Application\chrome.exe",
            @"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        };
        foreach (string exe in edges)
        {
            if (!File.Exists(exe)) continue;
            try
            {
                var psi = new ProcessStartInfo(exe, "--new-window \"" + url + "\"");
                psi.UseShellExecute = false;
                Process.Start(psi);
                if (WaitBrowser(before, 4)) { Log("  [OK] 用 " + Path.GetFileName(exe) + " 打开"); return true; }
                Log("  [--] " + Path.GetFileName(exe) + " 没起来");
            }
            catch (Exception e) { Log("  [--] " + exe + " 失败: " + e.Message); }
        }

        // ④ explorer（有些系统只能靠它走 shell 关联）
        try
        {
            Process.Start(new ProcessStartInfo("explorer.exe", "\"" + url + "\"") { UseShellExecute = false });
            if (WaitBrowser(before, 3)) { Log("  [OK] explorer 打开"); return true; }
            Log("  [--] explorer 没反应");
        }
        catch (Exception e) { Log("  [--] explorer 失败: " + e.Message); }

        // ⑤ 从注册表里读默认浏览器的启动命令
        try
        {
            string cmd = DefaultBrowserCommand();
            if (!string.IsNullOrEmpty(cmd))
            {
                Log("  注册表默认浏览器命令: " + cmd);
                string exe = cmd.StartsWith("\"") ? cmd.Substring(1, cmd.IndexOf('"', 1) - 1)
                                                  : cmd.Split(' ')[0];
                if (File.Exists(exe))
                {
                    Process.Start(new ProcessStartInfo(exe, "\"" + url + "\"") { UseShellExecute = false });
                    if (WaitBrowser(before, 4)) { Log("  [OK] 用注册表里的浏览器打开"); return true; }
                }
            }
        }
        catch (Exception e) { Log("  [--] 注册表方式失败: " + e.Message); }

        // 都失败：把地址放到剪贴板，并提示手动打开
        try { Clipboard.SetText(url); Log("  已把地址复制到剪贴板，请手动粘贴到浏览器"); } catch { }
        Log("  [X] 所有方式都没能打开浏览器，请手动访问: " + url);
        return false;
    }

    static bool WaitBrowser(int before, int seconds)
    {
        for (int i = 0; i < seconds * 4; i++)
        {
            Thread.Sleep(250);
            if (BrowserCount() > before) return true;
        }
        return false;
    }

    public static string DefaultBrowserCommand()
    {
        try
        {
            using (var k = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(
                @"SOFTWARE\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice"))
            {
                if (k == null) return null;
                string prog = k.GetValue("ProgId") as string;
                if (string.IsNullOrEmpty(prog)) return null;
                foreach (var root in new[] { Microsoft.Win32.Registry.ClassesRoot,
                                             Microsoft.Win32.Registry.CurrentUser })
                {
                    try
                    {
                        using (var c = root.OpenSubKey(prog + @"\shell\open\command"))
                        {
                            if (c != null) return c.GetValue(null) as string;
                        }
                    }
                    catch { }
                }
            }
        }
        catch { }
        return null;
    }

    /// <summary>启动中控台服务（若端口未监听），返回是否可用。</summary>
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
        // 中控台：按端口找 pid 结束
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
    Label lJudge, lConsole, lHint;
    TextBox box;
    Button bStart, bStop, bConsole, bFront;
    System.Windows.Forms.Timer timer;

    public MainForm()
    {
        Text = "OJ 判题机 · 后端中控台";
        ClientSize = new Size(560, 400);
        StartPosition = FormStartPosition.CenterScreen;
        Font = new Font("Microsoft YaHei UI", 9F);

        var title = new Label();
        title.Text = "一键启动：判题机 + 中控台";
        title.Font = new Font(Font.FontFamily, 13F, FontStyle.Bold);
        title.AutoSize = true; title.Location = new Point(16, 14);
        Controls.Add(title);

        lJudge = new Label(); lJudge.AutoSize = true; lJudge.Location = new Point(18, 52);
        lConsole = new Label(); lConsole.AutoSize = true; lConsole.Location = new Point(18, 76);
        lHint = new Label(); lHint.AutoSize = true; lHint.Location = new Point(18, 100);
        lHint.ForeColor = Color.DimGray;
        lHint.Text = "提示：中控台里可以调参数、看日志、暂停/恢复判题。";
        Controls.Add(lJudge); Controls.Add(lConsole); Controls.Add(lHint);

        bStart = new Button(); bStart.Text = "▶  一键启动"; bStart.Location = new Point(18, 130);
        bStart.Size = new Size(126, 36); bStart.Click += (s, e) => DoStart(true);
        bStop = new Button(); bStop.Text = "■  全部停止"; bStop.Location = new Point(152, 130);
        bStop.Size = new Size(126, 36); bStop.Click += (s, e) => DoStop();
        bConsole = new Button(); bConsole.Text = "打开中控台"; bConsole.Location = new Point(286, 130);
        bConsole.Size = new Size(120, 36);
        bConsole.Click += (s, e) => ThreadPool.QueueUserWorkItem(_ =>
        {
            OjEnv.EnsureConsole();
            OpenOnUiThread(OjEnv.ConsoleUrl);
        });
        bFront = new Button(); bFront.Text = "打开考生前端"; bFront.Location = new Point(414, 130);
        bFront.Size = new Size(128, 36);
        bFront.Click += (s, e) => OpenOnUiThread(OjEnv.FrontUrl);
        Controls.Add(bStart); Controls.Add(bStop); Controls.Add(bConsole); Controls.Add(bFront);

        var bCopy = new Button(); bCopy.Text = "复制中控台地址";
        bCopy.Location = new Point(18, 172); bCopy.Size = new Size(126, 26);
        bCopy.Click += (s, e) =>
        {
            try { Clipboard.SetText(OjEnv.ConsoleUrl); OjEnv.Log("已复制 " + OjEnv.ConsoleUrl); }
            catch (Exception ex) { OjEnv.Log("复制失败: " + ex.Message); }
        };
        var bProbe = new Button(); bProbe.Text = "重新探测浏览器";
        bProbe.Location = new Point(152, 172); bProbe.Size = new Size(140, 26);
        bProbe.Click += (s, e) => OpenOnUiThread(OjEnv.ConsoleUrl);
        Controls.Add(bCopy); Controls.Add(bProbe);

        box = new TextBox();
        box.Multiline = true; box.ScrollBars = ScrollBars.Vertical;
        box.Location = new Point(18, 208); box.Size = new Size(524, 174);
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
                OjEnv.Log("已经在运行中：直接点「打开中控台」即可");
            else
                DoStart(true);   // 双击即一键启动
        };
    }

    void Refresh2()
    {
        bool j = OjEnv.JudgeRunning(), c = OjEnv.PortOpen(OjEnv.ConsolePort, 250);
        int pid = OjEnv.JudgePid();
        lJudge.Text = "判题机：" + (j ? "运行中（pid=" + pid + "）" : "已停止");
        lJudge.ForeColor = j ? Color.SeaGreen : Color.Firebrick;
        lConsole.Text = "中控台：" + (c ? "运行中  " + OjEnv.ConsoleUrl : "已停止");
        lConsole.ForeColor = c ? Color.SeaGreen : Color.Firebrick;
    }

    void OpenOnUiThread(string url)
    {
        // ShellExecute 走的是 COM/STA，在线程池线程里调用可能静默失败，
        // 所以统一切回 UI 线程再打开。
        try
        {
            BeginInvoke(new Action(() =>
            {
                bool ok = OjEnv.OpenUrlVerbose(url);
                if (!ok)
                    MessageBox.Show("没能自动打开浏览器。\n\n地址已复制到剪贴板，请手动粘贴打开：\n" + url,
                                    "需要手动打开", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }));
        }
        catch
        {
            OjEnv.OpenUrlVerbose(url);
        }
    }

    void DoStart(bool openBrowser)
    {
        bStart.Enabled = false;
        ThreadPool.QueueUserWorkItem(_ =>
        {
            try
            {
                OjEnv.StartJudge();
                bool cok = OjEnv.EnsureConsole();
                if (cok && openBrowser) OpenOnUiThread(OjEnv.ConsoleUrl);
            }
            finally
            {
                try { BeginInvoke(new Action(() => { bStart.Enabled = true; Refresh2(); })); }
                catch { }
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
        bool headless = false, noBrowser = false, doStop = false, doStatus = false;
        string openUrl = null;
        for (int i = 0; i < args.Length; i++)
        {
            string s = args[i].ToLowerInvariant();
            if (s == "--start") headless = true;
            else if (s == "--no-browser") noBrowser = true;
            else if (s == "--stop") { headless = true; doStop = true; }
            else if (s == "--status") { headless = true; doStatus = true; }
            else if (s == "--open-url" && i + 1 < args.Length) { headless = true; openUrl = args[i + 1]; }
            else if (args[i].StartsWith("http")) { headless = true; openUrl = args[i]; }
        }

        if (headless)
        {
            OjEnv.Log("=== 命令行模式: " + string.Join(" ", args) + " ===");
            if (openUrl != null)
            {
                bool ok = OjEnv.OpenUrlVerbose(openUrl);
                OjEnv.Log("打开结果: " + (ok ? "成功" : "失败（地址已复制到剪贴板）"));
                return ok ? 0 : 1;
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
            if (okC && !noBrowser) OjEnv.OpenUrl(OjEnv.ConsoleUrl);
            OjEnv.Log("结果: 判题机=" + (okJ ? "OK" : "失败") + " 中控台=" + (okC ? "OK" : "失败"));
            return (okJ && okC) ? 0 : 1;
        }

        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new MainForm());
        return 0;
    }
}
