/* ============================================================================
 *  前端凭据配置（**本文件不入库**，复制 config.example.js 改成 config.js）
 *
 *  在 index.html 里、crypto.js 之前引入：
 *      <script src="assets/config.js"></script>
 *
 *  注意：这个文件会被浏览器下载给任何访问者，等于公开你的云端写权限。
 *        不要提交到公开仓库，不要发到公开网络。
 * ==========================================================================*/
window.OJ_CONFIG = {
  api: 'https://tinywebdb.appinventor.space/api',
  user: 'YOUR_USER',
  secret: 'YOUR_SECRET',
  minGapMs: 150,
  retries: 4,
  chunkChars: 8000
};
