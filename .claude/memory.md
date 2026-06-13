# CipherPipe 项目记忆

## 当前状态

- 三层传输已实现：Nostr relay 池 / LAN WS / Browser proxy
- 加密：NIP-44 (XChaCha20-Poly1305)，ECDH 密钥交换，BIP-340 Schnorr 签名
- relay: `relay.damus.io`, `nos.lol`, `relay.nostr.band`
- 单端口模式（8700 可配）正在推行，端口收敛中

## 关键设计决策

- **CipherPipe 只管管道**：不调 LLM API、不持 API key。AI 能力由外部进程注入
- **浏览器零加密逻辑**：密钥只存 proxy/cli，dashboard.html 只收发明文
- **无中心服务器**：身份 = Nostr 公钥，路由靠 relay `#p` tag 过滤
- **cli.py 是人类和 Agent 的通用客户端**：`--no-stdin` 模式给 agent 用

## 待办 / 方向

- LAN echo 模式未完成
- 端口收敛：8701/8702 → 统一 8700
