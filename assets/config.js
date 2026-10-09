/* ============================================================================
 *  前端云端连接配置（**有意入库**，公开部署时访问者打开即可用）
 *
 *  api    : TinyWebDB 接口地址
 *  user   : 实例用户名        <-- 拥有该实例的读写权限
 *  secret : 实例密钥          <-- 同上
 *
 *  说明：纯静态前端必须带上这套凭据才能直连云端 KV 与判题机通信，
 *        所以它会被浏览器下载给任何访问者，等同于"这个 OJ 的后台钥匙"。
 *        如果哪天要收回权限：TinyWebDB 侧重置密钥 -> 改这里（或改用页面里的
 *        「连接设置」让每个人填自己的实例）-> commit + push。
 *
 *  同时兼容浏览器与 Node（Node 下挂到 globalThis，供自测脚本使用）。
 * ==========================================================================*/
(function (root) {
  root.OJ_CONFIG = {
    api: 'https://tinywebdb.appinventor.space/api',
    user: 'ojojoj',
    secret: '8dc7ae54',
    minGapMs: 150,
    retries: 4,
    chunkChars: 8000
  };
})(typeof window !== 'undefined' ? window : globalThis);
