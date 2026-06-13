<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CipherPipe</title>
<script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
:root {
  --bg: #fff; --bg2: #f8f9fa; --border: #dee2e6;
  --text: #333; --text2: #868e96; --primary: #1f6feb;
  --msg-in: #f1f3f5; --msg-out: #dbeafe;
  --hover: #e9ecef; --danger: #e03131; --success: #2f9e44;
}
body.dark {
  --bg: #0d1117; --bg2: #161b22; --border: #30363d;
  --text: #c9d1d9; --text2: #8b949e; --primary: #58a6ff;
  --msg-in: #1c2128; --msg-out: #1f6feb22;
  --hover: #1c2128; --danger: #f85149; --success: #3fb950;
}
body { background:var(--bg); color:var(--text); font:14px/1.5 -apple-system,BlinkMacSystemFont,monospace; height:100vh; }
#app { display:flex; height:100vh; }
.sidebar { width:220px; background:var(--bg2); border-right:1px solid var(--border); display:flex; flex-direction:column; }
.sidebar h2 { padding:14px 16px 10px; font-size:16px; color:var(--primary); }
.sidebar-actions { padding:0 10px 8px; display:flex; gap:4px; }
.sidebar-actions button { flex:1; padding:5px; border:1px solid var(--border); border-radius:4px; background:var(--bg2); color:var(--text2); font-size:10px; cursor:pointer; }
.sidebar-actions button:hover { background:var(--hover); }
.search { margin:6px 10px; padding:6px 10px; border-radius:5px; border:1px solid var(--border); background:var(--bg); color:var(--text); font-size:12px; font-family:inherit; }
.search:focus { outline:none; border-color:var(--primary); }
.peers { flex:1; overflow-y:auto; padding:6px; }
.peer { padding:8px 10px; border-radius:5px; cursor:pointer; font-size:12px; display:flex; justify-content:space-between; align-items:center; }
.peer:hover { background:var(--hover); }
.peer.active { background:var(--msg-out); border:1px solid var(--primary); }
.peer .name { font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:130px; }
.peer .pk { color:var(--text2); font-size:10px; }
.peer .del { color:var(--danger); display:none; cursor:pointer; font-size:14px; }
.peer:hover .del { display:inline; }
.add-btn { margin:8px 10px; padding:7px 0; background:var(--primary); border:none; color:#fff; border-radius:5px; cursor:pointer; font-size:12px; text-align:center; }
.main { flex:1; display:flex; flex-direction:column; min-width:0; }
.header { padding:10px 16px; border-bottom:1px solid var(--border); background:var(--bg2); display:flex; justify-content:space-between; align-items:center; flex-shrink:0; }
.header .title { font-weight:600; font-size:14px; }
.header .status { font-size:11px; }
.status.on { color:var(--success); }
.status.off { color:var(--danger); }
.typing { font-size:11px; color:var(--text2); padding:4px 16px; height:22px; flex-shrink:0; }
.msgs { flex:1; overflow-y:auto; padding:12px 16px; display:flex; flex-direction:column; gap:4px; background:var(--bg); }
.msg { max-width:72%; padding:8px 12px; border-radius:8px; font-size:13px; animation: fadeIn .15s; position:relative; }
@keyframes fadeIn { from{opacity:0} to{opacity:1} }
.msg.in { align-self:flex-start; background:var(--msg-in); border:1px solid var(--border); }
.msg.out { align-self:flex-end; background:var(--msg-out); border:1px solid var(--primary); }
.msg .meta { font-size:10px; color:var(--text2); margin-bottom:3px; display:flex; justify-content:space-between; }
.msg .body { word-break:break-word; white-space:pre-wrap; }
.msg .rx { font-size:13px; margin-top:3px; }
.msg .actions { display:none; position:absolute; top:-14px; right:4px; background:var(--bg2); border:1px solid var(--border); border-radius:4px; padding:1px 2px; }
.msg:hover .actions { display:flex; gap:1px; }
.actions button { background:none; border:none; color:var(--text); font-size:11px; cursor:pointer; padding:1px 3px; }
.actions button:hover { background:var(--hover); border-radius:2px; }
.input-bar { padding:10px 16px; border-top:1px solid var(--border); background:var(--bg2); display:flex; gap:6px; flex-shrink:0; }
.input-bar input { flex:1; padding:8px 12px; border-radius:6px; border:1px solid var(--border); background:var(--bg); color:var(--text); font-family:inherit; font-size:13px; }
.input-bar input:focus { outline:none; border-color:var(--primary); }
.input-bar button { padding:8px 14px; border-radius:6px; border:none; cursor:pointer; font-family:inherit; font-size:13px; }
.btn-send { background:var(--primary); color:#fff; }
.btn-send:hover { opacity:0.85; }
.btn-file { background:var(--hover); color:var(--text); }
.btn-file:hover { opacity:0.7; }
.empty { color:var(--text2); text-align:center; margin-top:60px; line-height:1.8; }
.empty small { opacity:0.6; }
</style>
</head>
<body>
<div id="app">
  <div class="sidebar">
    <h2>CipherPipe</h2>
    <div class="sidebar-actions">
      <button @click="createIdentity">创建身份</button>
      <button @click="toggleTheme">{{ themeLabel }}</button>
    </div>
    <div v-if="myPubkey" style="padding:6px 10px;font-size:10px;color:var(--text2);word-break:break-all">
      我的公钥: {{ myPubkey }}
    </div>
    <input class="search" v-model="searchQuery" placeholder="搜索消息..." @input="search">
    <div class="peers">
      <div v-for="p in peers" :key="p.pubkey"
           :class="['peer', {active: currentPeer === p.pubkey}]"
           @click="switchPeer(p.pubkey)">
        <div>
          <div class="name">{{ p.petname || p.pubkey.slice(0,12)+'...' }}</div>
          <div class="pk">{{ p.pubkey.slice(0,8) }}...</div>
        </div>
        <span class="del" @click.stop="delPeer(p.pubkey)">✕</span>
      </div>
    </div>
    <div class="add-btn" @click="addPeer">+ 添加联系人</div>
  </div>

  <div class="main">
    <div class="header">
      <span class="title">{{ chatTitle }}</span>
      <span :class="['status', statusClass]">{{ statusText }}</span>
    </div>
    <div class="typing">{{ typingText }}</div>
    <div class="msgs" ref="msgContainer">
      <div v-if="!currentPeer" class="empty">
        添加联系人公钥开始聊天<br>
        <small>NIP-44 端到端加密 · Nostr 全球 relay</small>
      </div>
      <div v-for="m in messages" :key="m.id"
           :class="['msg', m.dir]"
           @mouseenter="m.hover=true" @mouseleave="m.hover=false">
        <div v-if="m.hover" class="actions">
          <button @click="react(m, '👍')">👍</button>
          <button @click="react(m, '❤️')">❤️</button>
          <button @click="react(m, '😂')">😂</button>
          <button @click="react(m, '🔥')">🔥</button>
          <button @click="delMsg(m)">✕</button>
        </div>
        <div class="meta">
          <span>{{ m.dir === 'out' ? 'me' : m.from }} 🔒</span>
          <span v-if="m.dir==='out'" :style="{color: m.delivered ? '#58a6ff' : '#8b949e', fontSize:'10px'}">✓</span>
        </div>
        <div class="body">{{ m.text }}</div>
        <div v-if="m.reactions" class="rx">{{ m.reactions }}</div>
      </div>
    </div>
    <div class="input-bar">
      <input v-model="inputText" :disabled="!currentPeer" placeholder="消息..."
             @keydown.enter="send" @input="onTyping">
      <button class="btn-file" @click="sendFile" title="发送文件">+</button>
      <button class="btn-send" @click="send" :disabled="!currentPeer">发送</button>
    </div>
  </div>
</div>

<script>
const { createApp, ref, computed, nextTick, watch, onMounted } = Vue;

createApp({
  setup() {
    const ws = ref(null);
    const currentPeer = ref(null);
    const myPubkey = ref(localStorage.getItem('cp_my_pubkey') || '');
    const peers = ref(JSON.parse(localStorage.getItem('cp_peers') || '[]').map(p => typeof p === 'string' ? {pubkey:p, petname:''} : p));
    const messages = ref([]);
    const inputText = ref('');
    const searchQuery = ref('');
    const statusText = ref('disconnected');
    const statusClass = ref('off');
    const typingText = ref('');
    const msgContainer = ref(null);
    let typingTimeout = null;
    let msgId = 0;
    let savedMessages = [];
    let isSearching = false;

    const dark = ref(localStorage.getItem('cp_dark') === '1');
    const themeLabel = computed(() => dark.value ? '日间模式' : '夜间模式');
    function toggleTheme() {
      dark.value = !dark.value;
      localStorage.setItem('cp_dark', dark.value ? '1' : '0');
      document.body.classList.toggle('dark', dark.value);
    }
    if (dark.value) document.body.classList.add('dark');

    const chatTitle = computed(() => {
      if (!currentPeer.value) return '选择联系人';
      const p = peers.value.find(x => x.pubkey === currentPeer.value);
      return p && p.petname ? p.petname : currentPeer.value.slice(0,12) + '...';
    });

    function connect() {
      if (ws.value) ws.value.close();
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      ws.value = new WebSocket(`${proto}//${location.host}/ws`);
      ws.value.onopen = () => {
        statusText.value = 'connected';
        statusClass.value = 'on';
        if (Notification.permission === 'default') Notification.requestPermission();
      };
      ws.value.onclose = () => {
        statusText.value = 'disconnected';
        statusClass.value = 'off';
        setTimeout(connect, 3000);
      };
      ws.value.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        if (msg.type === 'identity_created') {
          myPubkey.value = msg.pubkey;
          localStorage.setItem('cp_my_pubkey', msg.pubkey);
          ws.value.send(JSON.stringify({type:'lan_hello', pubkey: msg.pubkey}));
          return;
        }
        if (msg.type === 'identity') {
          if (myPubkey.value) {
            ws.value.send(JSON.stringify({type:'lan_hello', pubkey: myPubkey.value}));
          } else {
            ws.value.send(JSON.stringify({type:'create_identity'}));
          }
          return;
        }
        if (msg.type === 'typing') {
          typingText.value = msg.from + ' 正在输入...';
          clearTimeout(typingTimeout);
          typingTimeout = setTimeout(() => { typingText.value = ''; }, 3000);
          return;
        }
        if (msg.type === 'file') {
          addMsg(msg.from, `[file: ${msg.name} (${(msg.size/1024).toFixed(1)}KB)]`, 'in', msg.id);
          return;
        }
        if (msg.type === 'file_ok') {
          const lastOut = [...messages.value].reverse().find(x => x.dir === 'out' && !x.delivered);
          if (lastOut) { lastOut.id = msg.name; lastOut.delivered = true; }
          return;
        }
        if (msg.type === 'error') {
          addMsg('system', msg.msg, 'in');
          return;
        }
        if (msg.type === 'reaction') {
          const m = messages.value.find(x => x.id === msg.event_id);
          if (m) m.reactions = (m.reactions || '') + msg.emoji;
          return;
        }
        if (msg.type === 'msg' || msg.from) {
          if (msg.from === 'me') {
            // Echo from proxy — update last outgoing with real id and delivered status
            const lastOut = [...messages.value].reverse().find(x => x.dir === 'out' && !x.id);
            if (lastOut) {
              lastOut.id = msg.id || lastOut.id;
              lastOut.delivered = msg.delivered;
            }
            return;
          }
          addMsg(msg.from, msg.text, 'in', msg.id);
          if (document.hidden && Notification.permission === 'granted') {
            new Notification('CipherPipe: ' + msg.from, {body: msg.text.slice(0, 100)});
          }
        }
        if (msg.type === 'search_results') {
          messages.value = [];
          if (msg.data && msg.data.length > 0) {
            for (const m of msg.data) {
              addMsg(m.pubkey.slice(0,12), m.content, m.direction, m.event_id);
            }
          }
        }
        if (msg.type === 'history') {
          if (msg.data) {
            for (const m of msg.data) {
              addMsg(m.pubkey.slice(0,12), m.content, m.direction, m.event_id, true, m.delivered);
            }
          }
        }
      };
    }

    function createIdentity() {
      if (!ws.value || ws.value.readyState !== WebSocket.OPEN) return;
      ws.value.send(JSON.stringify({type:'create_identity'}));
    }

    function addMsg(from, text, dir, eventId, prepend = false, delivered = false) {
      const m = { id: eventId || 'm' + (++msgId), from, text, dir, delivered, reactions: '', hover: false };
      if (prepend) messages.value.unshift(m);
      else messages.value.push(m);
      nextTick(() => {
        if (msgContainer.value) msgContainer.value.scrollTop = msgContainer.value.scrollHeight;
      });
    }

    function send() {
      const text = inputText.value.trim();
      if (!text || !ws.value || ws.value.readyState !== WebSocket.OPEN || !currentPeer.value) return;
      addMsg('me', text, 'out');
      ws.value.send(JSON.stringify({type:'msg', text, to: currentPeer.value}));
      inputText.value = '';
    }

    function sendFile() {
      const inp = document.createElement('input');
      inp.type = 'file';
      inp.onchange = async () => {
        const file = inp.files[0];
        if (!file || !currentPeer.value) return;
        const buf = await file.arrayBuffer();
        ws.value.send(JSON.stringify({type:'file', name:file.name, size:buf.byteLength, to: currentPeer.value}));
        ws.value.send(buf);
        addMsg('me', `[文件: ${file.name} (${(file.size/1024).toFixed(1)}KB)]`, 'out');
      };
      inp.click();
    }

    function onTyping() {
      if (!ws.value || ws.value.readyState !== WebSocket.OPEN || !currentPeer.value) return;
      ws.value.send(JSON.stringify({type:'typing', to: currentPeer.value}));
    }

    function react(m, emoji) {
      if (!ws.value || !currentPeer.value) return;
      m.reactions = (m.reactions || '') + emoji;
      ws.value.send(JSON.stringify({type:'reaction', peer: currentPeer.value, event_id: m.id, emoji}));
    }

    function delMsg(m) {
      messages.value = messages.value.filter(x => x.id !== m.id);
      if (ws.value && currentPeer.value) {
        ws.value.send(JSON.stringify({type:'delete_msg', event_id: m.id, peer: currentPeer.value}));
      }
    }

    function addPeer() {
      const pubkey = prompt('对方公钥 (hex):');
      if (!pubkey) return;
      const petname = prompt('别名 (可选):') || '';
      const existing = peers.value.find(p => p.pubkey === pubkey);
      if (existing) { existing.petname = petname; }
      else { peers.value.push({pubkey, petname}); }
      savePeers();
      switchPeer(pubkey);
    }

    function delPeer(pubkey) {
      peers.value = peers.value.filter(p => p.pubkey !== pubkey);
      if (currentPeer.value === pubkey) currentPeer.value = null;
      savePeers();
    }

    function switchPeer(pubkey) {
      currentPeer.value = pubkey;
      messages.value = [];
      typingText.value = '';
      isSearching = false;
      searchQuery.value = '';
      if (ws.value && ws.value.readyState === WebSocket.OPEN) {
        ws.value.send(JSON.stringify({type:'history', peer: pubkey, limit: 50}));
      }
    }

    function savePeers() {
      localStorage.setItem('cp_peers', JSON.stringify(peers.value));
    }

    function search() {
      if (!searchQuery.value) {
        if (isSearching) { messages.value = [...savedMessages]; isSearching = false; }
        return;
      }
      if (!ws.value || ws.value.readyState !== WebSocket.OPEN) return;
      if (!isSearching) { savedMessages = [...messages.value]; isSearching = true; }
      ws.value.send(JSON.stringify({type:'search', query: searchQuery.value}));
    }

    onMounted(() => { connect(); });

    return {
      currentPeer, myPubkey, peers, messages, inputText, searchQuery, statusText, statusClass,
      typingText, chatTitle, msgContainer, themeLabel, toggleTheme,
      send, sendFile, onTyping, react, delMsg, addPeer, delPeer, switchPeer, search, createIdentity
    };
  }
}).mount('#app');
</script>
</body>
</html>
