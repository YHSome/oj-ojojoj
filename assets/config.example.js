/* ============================================================================
 *  前端凭据配置示例（**本文件是占位版，可以入库**）
 *
 *  用法：复制成 config.js 再填真实值（config.js 已被 .gitignore 排除）
 *        <script src="assets/config.js"></script>   ← 放在 crypto.js 之前
 *
 *  注意：这个文件会被浏览器下载给任何访问者，等于公开你的云端写权限。
 *        不要提交真实值，不要发到公开网络。详见 assets/config.example.html
 * ==========================================================================*/
(function (root) {
  root.OJ_CONFIG = {
    api: 'https://tinywebdb.appinventor.space/api',
    user: 'YOUR_USER',
    secret: 'YOUR_SECRET',
    minGapMs: 150,
    retries: 4,
    chunkChars: 8000
  };
})(typeof window !== 'undefined' ? window : globalThis);
