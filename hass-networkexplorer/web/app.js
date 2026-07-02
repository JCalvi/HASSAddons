let rows=[], sortKey="ip", asc=true, expandedKey="";
let setupDevices=[];
let autoRefreshTimer=null;
const $ = id => document.getElementById(id);

function addonBase(){
  const p = window.location.pathname || "/";
  return p.endsWith("/") ? p : p + "/";
}
function apiPath(path){return addonBase() + String(path||"").replace(/^\//, "");}
function esc(s){return String(s||"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[m]));}
function ipVal(ip){
  const p=String(ip||"999.999.999.999").split(".").map(x=>parseInt(x,10));
  return [p[0]||999,p[1]||999,p[2]||999,p[3]||999];
}
function ipCmp(a,b){let A=ipVal(a),B=ipVal(b);for(let i=0;i<4;i++)if(A[i]!==B[i])return A[i]-B[i];return 0;}
function cmp(a,b){
  if(sortKey==="ip") return ipCmp(a.ip,b.ip);
  if(sortKey==="rssi")return(parseInt(a.rssi)||-999)-(parseInt(b.rssi)||-999);
  return String(a[sortKey]||"").localeCompare(String(b[sortKey]||""));
}
function persistView(){
  localStorage.setItem("networkExplorerView", JSON.stringify({
    search:$("search")?.value||"", status:$("statusFilter")?.value||"", connection:$("connectionFilter")?.value||"", ap:$("apFilter")?.value||"", sortKey, asc, expandedKey
  }));
}
function restoreView(){
  try{
    const v=JSON.parse(localStorage.getItem("networkExplorerView")||"{}");
    if(v.search!==undefined)$("search").value=v.search;
    if(v.status!==undefined)$("statusFilter").value=v.status;
    if(v.connection!==undefined)$("connectionFilter").value=v.connection;
    if(v.ap!==undefined)$("apFilter").value=v.ap;
    if(v.sortKey)sortKey=v.sortKey;
    if(v.asc!==undefined)asc=!!v.asc;
    if(v.expandedKey)expandedKey=v.expandedKey;
  }catch(e){}
}
function sortBy(k){asc=sortKey===k?!asc:true;sortKey=k;persistView();render();}
function rssiClass(v){let n=parseInt(v);if(!n)return"";if(n>=-60)return"rssi-good";if(n>=-72)return"rssi-ok";return"rssi-bad";}
async function postJson(url,obj){const r=await fetch(apiPath(url),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(obj||{})});const d=await r.json();if(!d.ok)throw new Error(d.error||"Request failed");return d;}
function defaultDevice(type){return {type:type||"Auto",name:"",ip:"",user:"root",password:"",ssh:"unknown",message:"",detail:"",detected_os:"",install_path:""};}
function sortSetupDevices(){setupDevices.sort((a,b)=>ipCmp(a.ip,b.ip)||String(a.name||"").localeCompare(String(b.name||"")));}
function setSetupMessage(msg, kind="info"){$("setupStatus").className=`setup-status ${kind}`;$('setupStatus').textContent=msg||"";}
function setSetupOutput(obj){$("setupOutput").textContent=typeof obj==="string"?obj:JSON.stringify(obj,null,2);}
function showKeyInfo(key){if(!key){$("keyInfo").textContent="";return;}$("keyInfo").innerHTML=`<div><b>SSH key:</b> ${esc(key.exists?"created":"missing")} - ${esc(key.private_key||"")}</div><div><b>Public key:</b></div><code>${esc(key.public_key_text||"")}</code>`;}
function shortError(s){s=String(s||"").trim();if(!s)return"Failed";if(/Permission denied/i.test(s))return"Authentication failed";if(/Connection refused/i.test(s))return"Connection refused";if(/timed out|timeout/i.test(s))return"Connection timeout";if(/No route to host/i.test(s))return"No route to host";if(/Name or service not known|Could not resolve/i.test(s))return"Could not resolve host";return s.split("\n").map(x=>x.trim()).filter(Boolean).pop().slice(0,80)||"Failed";}
function deviceTypeClass(t){return (t||"Host").toLowerCase().replace(/[^a-z0-9]+/g,"-");}
function copyText(text,label){if(!text)return; navigator.clipboard?.writeText(text).then(()=>{$("updated").textContent=`Copied ${label||"text"}: ${text}`;}).catch(()=>{});}
function deviceKey(x){return x.mac || x.ip || x.host || "";}
function enrichSeen(items){
  let seen={};
  try{seen=JSON.parse(localStorage.getItem("networkExplorerSeen")||"{}");}catch(e){seen={};}
  const now=new Date().toISOString();
  (items||[]).forEach(x=>{
    const k=deviceKey(x); if(!k)return;
    if(!seen[k]) seen[k]={first_seen:now,last_seen:now};
    if(x.status==="online") seen[k].last_seen=now;
    x.first_seen=seen[k].first_seen;
    x.last_seen=seen[k].last_seen;
  });
  localStorage.setItem("networkExplorerSeen", JSON.stringify(seen));
  return items;
}
function setupPayload(includePasswords=true){
  updateAllSetupDevices();
  return {
    devices: setupDevices.map(d=>({type:d.type,name:d.name,ip:d.ip,user:d.user,password:includePasswords?d.password:""})),
    piholes: setupDevices.filter(d=>d.type==="Pi-hole"&&d.ip).map(d=>d.ip),
    access_points: setupDevices.filter(d=>["OpenWrt Wi-Fi","OpenWrt AP"].includes(d.type)&&d.ip).map(d=>d.ip),
    ssh_key_path: $("sshKeyPathInput").value.trim()||"/config/ssh/id_ed25519"
  };
}
function updateDeviceFromRow(i){
  const row=document.querySelector(`tr[data-setup-index="${i}"]`); if(!row) return;
  setupDevices[i].type=row.querySelector(".dev-type").value;
  setupDevices[i].name=row.querySelector(".dev-name").value.trim();
  setupDevices[i].ip=row.querySelector(".dev-ip").value.trim();
  setupDevices[i].user=row.querySelector(".dev-user").value.trim()||"root";
  setupDevices[i].password=row.querySelector(".dev-password").value;
}
function updateAllSetupDevices(){setupDevices.forEach((_,i)=>updateDeviceFromRow(i));sortSetupDevices();}
function statusChip(d){
  if(d.ssh==="ok") return `<span class="chip ok">Connected</span>`;
  if(d.ssh==="fail") return `<span class="chip bad">${esc(shortError(d.message||d.detail))}</span>`;
  if(d.ssh==="installing") return `<span class="chip wait">Installing...</span>`;
  if(d.ssh==="testing") return `<span class="chip wait">Testing...</span>`;
  return `<span class="chip unknown">Unknown</span>`;
}
function renderSetupSummary(){
  const total=setupDevices.filter(d=>d.ip).length;
  const ok=setupDevices.filter(d=>d.ip&&d.ssh==="ok").length;
  if(total && ok===total){$("setupIntro").innerHTML=`<span class="ok-text">${ok} of ${total} devices configured.</span>`;}
  else{$("setupIntro").textContent="Each device can use its own username and one-time password. Passwords are not saved.";}
  const hidden=$("setupPanel").classList.contains("collapsed");
  $("settingsBtn").textContent=hidden?"Settings":"Hide Settings";
  $("toggleSetupBtn").textContent="Hide Settings";
}
function renderSetupDevices(){
  sortSetupDevices();
  $("setupDevices").innerHTML=setupDevices.map((d,i)=>{
    const installed=d.ssh==="ok";
    const detail=d.detail||d.message||"";
    return `<tr data-setup-index="${i}">
      <td><select class="dev-type type-${deviceTypeClass(d.type)}"><option ${d.type==="Auto"?"selected":""}>Auto</option><option ${d.type==="Pi-hole"?"selected":""}>Pi-hole</option><option ${d.type==="OpenWrt Wi-Fi"||d.type==="OpenWrt AP"?"selected":""}>OpenWrt Wi-Fi</option><option ${d.type==="OpenWrt"?"selected":""}>OpenWrt</option><option ${d.type==="Linux"||d.type==="Host"?"selected":""}>Linux</option></select></td>
      <td><input class="dev-name" value="${esc(d.name)}" placeholder="auto"></td>
      <td><input class="dev-ip" value="${esc(d.ip)}" placeholder="192.168.1.x"></td>
      <td><input class="dev-user" value="${esc(d.user||"root")}" placeholder="root"></td>
      <td><input class="dev-password" type="password" value="${esc(d.password||"")}" placeholder="${installed?"installed":"not saved"}" ${installed?"disabled":""}></td>
      <td class="ssh-status">${statusChip(d)}${d.detected_os?`<small>${esc(d.detected_os)}${d.install_path?` - ${esc(d.install_path)}`:""}</small>`:""}${d.ssh==="fail"&&detail?`<button class="link-button show-detail" type="button">Details</button>`:""}</td>
      <td class="row-actions"><button class="secondary install-one" type="button">Install Key</button><button class="secondary test-one" type="button">Test</button><button class="danger remove-one" type="button">Remove</button></td>
    </tr>`;
  }).join("");
  document.querySelectorAll("#setupDevices tr").forEach(row=>{
    const i=parseInt(row.dataset.setupIndex);
    row.querySelectorAll("input,select").forEach(el=>el.addEventListener("input",()=>updateDeviceFromRow(i)));
    row.querySelector(".remove-one").addEventListener("click",e=>{e.preventDefault();setupDevices.splice(i,1);renderSetupDevices();});
    row.querySelector(".install-one").addEventListener("click",e=>{e.preventDefault();installOne(i).catch(err=>setSetupMessage(err.message,"bad"));});
    row.querySelector(".test-one").addEventListener("click",e=>{e.preventDefault();testOne(i).catch(err=>setSetupMessage(err.message,"bad"));});
    const detail=row.querySelector(".show-detail");
    if(detail) detail.addEventListener("click",e=>{e.preventDefault();$("diagnosticsPanel").open=true;setSetupOutput(setupDevices[i].detail||setupDevices[i].message||"");});
  });
  renderSetupSummary();
}
function mergeStatuses(results){
  (results||[]).forEach(r=>{
    const d=setupDevices.find(x=>x.ip===r.ip); if(!d) return;
    d.ssh=(r.ok&&(r.key_ok===undefined||r.key_ok))?"ok":"fail";
    d.detected_os=r.detected_os||d.detected_os||"";
    d.install_path=r.install_path||d.install_path||"";
    const meta=[];
    if(r.detected_os) meta.push(`Detected OS: ${r.detected_os}`);
    if(r.profile) meta.push(`Profile: ${r.profile}`);
    if(r.install_path) meta.push(`Key path: ${r.install_path}`);
    if(r.os_detail) meta.push(`OS detail:\n${r.os_detail}`);
    const raw=r.error||r.host||"";
    d.message=d.ssh==="ok"?(r.host||r.detected_os||"Connected"):shortError(r.error||"Failed");
    d.detail=[raw,...meta].filter(Boolean).join("\n\n");
    if(r.host && !d.name)d.name=r.host;
    if(r.type&&r.type!=="Unknown")d.type=r.type;
    d.password="";
  });
  renderSetupDevices();
}
async function loadConfig(){
  try{
    const r=await fetch(apiPath("api/config?_="+Date.now()),{cache:"no-store"}); const d=await r.json(); if(!d.ok)throw new Error(d.error||"Config failed");
    const c=d.config||{}; $("sshKeyPathInput").value=c.ssh_key_path||"/config/ssh/id_ed25519";
    setupDevices=(c.devices&&c.devices.length?c.devices:[]).map(x=>({...defaultDevice(x.type),...x,password:"",ssh:"unknown",message:"",detail:""}));
    if(!setupDevices.length){
      (c.piholes||[]).forEach(ip=>setupDevices.push({...defaultDevice("Pi-hole"),ip}));
      (c.access_points||[]).forEach(ip=>setupDevices.push({...defaultDevice("OpenWrt Wi-Fi"),ip}));
    }
    renderSetupDevices(); showKeyInfo(d.key); testAll(false).catch(()=>{});
  }catch(e){setSetupMessage("Config load failed: "+e.message,"bad");}
}
async function saveConfig(show=true){const d=await postJson("api/config",setupPayload(false));showKeyInfo(d.key); if(show){setSetupMessage("Configuration saved.","ok");setSetupOutput(d.config||{});} return d;}
async function generateKey(){await saveConfig(false); setSetupMessage("Generating SSH key...","info");const d=await postJson("api/ssh/generate",{}); showKeyInfo(d.key); setSetupMessage("SSH key ready.","ok"); setSetupOutput(d.key||{}); return d;}
async function installOne(i){updateDeviceFromRow(i); const dev=setupDevices[i]; if(!dev.ip){setSetupMessage("IP address required.","bad");return;} if(!dev.password){setSetupMessage(`Password required for ${dev.ip}.`,"bad");return;} dev.ssh="installing";dev.message="Installing key";dev.detail="";renderSetupDevices(); const payload=setupPayload(true); payload.ip=dev.ip; const d=await postJson("api/ssh/install_one",payload); mergeStatuses(d.results); showKeyInfo(d.key); setSetupOutput(d.results||[]); const r=(d.results||[]).find(x=>x.ip===dev.ip); setSetupMessage(r&&r.ok?`SSH key installed on ${dev.ip}.`:`Install failed for ${dev.ip}.`,r&&r.ok?"ok":"bad");}
async function installAll(){updateAllSetupDevices(); setSetupMessage("Installing SSH keys...","info"); setupDevices.forEach(d=>{if(d.ip&&d.password){d.ssh="installing";d.message="Installing key";}});renderSetupDevices(); const d=await postJson("api/ssh/install_all",setupPayload(true)); mergeStatuses(d.results); showKeyInfo(d.key); setSetupOutput(d.results||[]); const ok=(d.results||[]).filter(x=>x.ok&&x.key_ok!==false).length; const total=(d.results||[]).length; setSetupMessage(`${ok} of ${total} SSH keys installed/tested successfully.`,ok===total?"ok":"bad");}
async function testOne(i){updateDeviceFromRow(i); const dev=setupDevices[i]; if(!dev.ip){setSetupMessage("IP address required.","bad");return;} dev.ssh="testing";dev.message="Testing";dev.detail="";renderSetupDevices(); const payload=setupPayload(false); payload.devices=[{type:dev.type,name:dev.name,ip:dev.ip,user:dev.user,password:""}]; const d=await postJson("api/ssh/test",payload); mergeStatuses(d.results); setSetupOutput(d.results||[]); const r=(d.results||[]).find(x=>x.ip===dev.ip); setSetupMessage(r&&r.ok?`${dev.ip} connected.`:`${dev.ip} failed: ${shortError(r&&r.error)}`,r&&r.ok?"ok":"bad");}
async function testAll(show=true){updateAllSetupDevices(); if(show)setSetupMessage("Testing SSH connections...","info"); setupDevices.forEach(d=>{if(d.ip){d.ssh="testing";d.message="Testing";}});renderSetupDevices(); const d=await postJson("api/ssh/test",setupPayload(false)); mergeStatuses(d.results); setSetupOutput(d.results||[]); const ok=(d.results||[]).filter(x=>x.ok).length; const total=(d.results||[]).length; if(show)setSetupMessage(`${ok} of ${total} SSH connections OK.`,ok===total?"ok":"bad");}
function fillFilters(){
  const c=$("connectionFilter"), a=$("apFilter"); const cv=c.value, av=a.value;
  const conns=[...new Set(rows.map(x=>x.connection).filter(Boolean))].sort(); const aps=[...new Set(rows.map(x=>x.ap).filter(Boolean))].sort();
  c.innerHTML='<option value="">All connections</option><option value="__wifi__">All Wi-Fi</option>'+conns.map(x=>`<option>${esc(x)}</option>`).join("");
  a.innerHTML='<option value="">All APs</option>'+aps.map(x=>`<option>${esc(x)}</option>`).join("");
  c.value=[...c.options].some(o=>o.value===cv)?cv:""; a.value=[...a.options].some(o=>o.value===av)?av:"";
}
function statusText(x){return x.status==="online"?"Online":x.status==="idle"?"Idle":"Offline";}
function seenText(s){if(!s)return"";try{return new Date(s).toLocaleString();}catch(e){return s;}}
function detailHtml(x){
  const ip=esc(x.ip), host=esc(x.host), mac=esc(x.mac);
  const actions=[];
  if(x.ip){
    actions.push(`<button class="detail-action open-http" data-ip="${ip}" type="button">Open http://${ip}</button>`);
    actions.push(`<button class="detail-action open-https" data-ip="${ip}" type="button">Open https://${ip}</button>`);
    actions.push(`<button class="detail-action copy-value" data-label="IP" data-copy="${ip}" type="button">Copy IP</button>`);
  }
  if(x.host) actions.push(`<button class="detail-action copy-value" data-label="hostname" data-copy="${host}" type="button">Copy Host</button>`);
  if(x.mac) actions.push(`<button class="detail-action copy-value" data-label="MAC" data-copy="${mac}" type="button">Copy MAC</button>`);
  return `<tr class="detail"><td colspan="9"><b>${esc(x.host||x.ip||x.mac||"Unknown device")}</b><div class="detail-actions">${actions.join("")}</div><div class="detail-grid"><div>IP</div><div>${ip}</div><div>Host</div><div>${host}</div><div>MAC</div><div>${mac}</div><div>Status</div><div>${esc(statusText(x))}</div><div>Connection</div><div>${esc(x.connection)}</div><div>AP</div><div>${esc(x.ap)}</div><div>Band</div><div>${esc(x.band)}</div><div>RSSI</div><div>${esc(x.rssi?x.rssi+" dBm":"")}</div><div>Ping</div><div>${esc(x.ping)}</div><div>TCP</div><div>${esc(x.tcp)}</div><div>First Seen</div><div>${esc(seenText(x.first_seen))}</div><div>Last Seen</div><div>${esc(seenText(x.last_seen))}</div><div>Neighbour State</div><div>${esc(x.neighbour_state)}</div><div>Last Wi-Fi Event</div><div>${esc(x.wifi_last_event)}</div><div>Last Wi-Fi Seen</div><div>${esc(x.wifi_last_seen)}</div><div>Source</div><div>${esc(x.source)}</div></div></td></tr>`;
}

function clearFilters(){
  $("search").value="";
  $("statusFilter").value="";
  $("connectionFilter").value="";
  $("apFilter").value="";
  persistView();
  render();
}
function render(){
  persistView();
  let q=$("search").value.toLowerCase(), status=$("statusFilter").value, conn=$("connectionFilter").value, ap=$("apFilter").value;
  let out=rows.filter(x=>{
    let blob=Object.values(x).join(" ").toLowerCase();
    if(q&&!blob.includes(q))return false;
    if(status&&x.status!==status)return false;
    if(conn==="__wifi__"){if(!x.connection||x.connection==="Ethernet"||x.connection==="Tailscale")return false;}
    else if(conn&&x.connection!==conn)return false;
    if(ap&&x.ap!==ap)return false;
    return true;
  }).sort((a,b)=>asc?cmp(a,b):-cmp(a,b));
  $("body").innerHTML=out.map(x=>{const key=`${x.ip}|${x.mac}`;const open=expandedKey===key;return `<tr class="mainrow" data-key="${esc(key)}"><td>${esc(x.ip)}</td><td>${esc(x.host)}</td><td>${esc(x.mac)}</td><td><span class="status-pill ${esc(x.status)}">${esc(statusText(x))}</span></td><td>${esc(x.connection)}</td><td>${esc(x.ap)}</td><td>${esc(x.band)}</td><td class="${rssiClass(x.rssi)}">${esc(x.rssi)}</td><td>${esc(x.source)}</td></tr>${open?detailHtml(x):""}`;}).join("");
  document.querySelectorAll(".mainrow").forEach(row=>row.addEventListener("click",e=>{if(e.target.closest("button"))return;expandedKey=expandedKey===row.dataset.key?"":row.dataset.key;persistView();render();}));
  document.querySelectorAll(".open-http").forEach(b=>b.addEventListener("click",e=>{e.preventDefault();e.stopPropagation();window.open(`http://${b.dataset.ip}`,"_blank");}));
  document.querySelectorAll(".open-https").forEach(b=>b.addEventListener("click",e=>{e.preventDefault();e.stopPropagation();window.open(`https://${b.dataset.ip}`,"_blank");}));
  document.querySelectorAll(".copy-value").forEach(b=>b.addEventListener("click",e=>{e.preventDefault();e.stopPropagation();copyText(b.dataset.copy,b.dataset.label||"text");}));
  const online=rows.filter(x=>x.status==="online").length, idle=rows.filter(x=>x.status==="idle").length, offline=rows.filter(x=>x.status==="offline").length;
  const wifi=rows.filter(x=>x.status==="online"&&x.connection&&x.connection!=="Ethernet"&&x.connection!=="Tailscale").length;
  const wired=rows.filter(x=>x.status==="online"&&x.connection==="Ethernet").length;
  const tailscale=rows.filter(x=>x.status==="online"&&x.connection==="Tailscale").length;
  $("updated").textContent=`Updated ${new Date().toLocaleTimeString()} - ${out.length}/${rows.length} shown`;
  $("summary").innerHTML=`<span class="summary-chip" data-filter="all">${rows.length} devices</span><span class="summary-chip" data-status="online">${online} online</span><span class="summary-chip" data-status="idle">${idle} idle</span><span class="summary-chip" data-status="offline">${offline} offline</span><span class="summary-chip" data-connection="__wifi__">Wi-Fi ${wifi}</span><span class="summary-chip" data-connection="Ethernet">Ethernet ${wired}</span><span class="summary-chip" data-connection="Tailscale">Tailscale ${tailscale}</span>`;
  document.querySelectorAll(".summary-chip").forEach(chip=>chip.addEventListener("click",()=>{
    if(chip.dataset.filter==="all"){clearFilters();return;}
    if(chip.dataset.status){$("statusFilter").value=chip.dataset.status;$("connectionFilter").value="";$("apFilter").value="";}
    if(chip.dataset.connection){$("statusFilter").value="online";$("connectionFilter").value=chip.dataset.connection;$("apFilter").value="";}
    persistView();render();
  }));
}
async function load(){const btn=$("refreshBtn"); btn.disabled=true; btn.textContent="Refreshing..."; $("updated").textContent="Refreshing..."; try{const r=await fetch(apiPath("api/refresh?_="+Date.now()),{cache:"no-store"}); const data=await r.json(); if(!data.ok) throw new Error(data.error||"Refresh failed"); rows=enrichSeen(data.devices||[]); fillFilters(); restoreView(); render();}catch(e){$("updated").textContent="Refresh failed: "+e.message;} btn.disabled=false; updateRefreshButtonLabel();}
function setSetupCollapsed(collapsed){$("setupPanel").classList.toggle("collapsed", collapsed);localStorage.setItem("networkExplorerSetupCollapsed", collapsed?"1":"0");renderSetupSummary();}
function applyTheme(theme){document.documentElement.dataset.theme=theme;localStorage.setItem("networkExplorerTheme",theme);$("themeSelect").value=theme;}
function refreshLabel(seconds){return seconds>0?`Refresh (${seconds>=60?seconds/60+"m":seconds+"s"})`:"Refresh";}
function updateRefreshButtonLabel(){const seconds=parseInt($("autoRefreshSelect").value,10)||0;$("refreshBtn").textContent=refreshLabel(seconds);}
function setupAutoRefresh(){
  if(autoRefreshTimer){clearInterval(autoRefreshTimer);autoRefreshTimer=null;}
  const seconds=parseInt($("autoRefreshSelect").value,10)||0;
  localStorage.setItem("networkExplorerAutoRefresh",String(seconds));
  updateRefreshButtonLabel();
  if(seconds>0){autoRefreshTimer=setInterval(()=>{if(!document.hidden)load();},seconds*1000);}
}

document.addEventListener("DOMContentLoaded",()=>{
  applyTheme(localStorage.getItem("networkExplorerTheme")||"auto");
  restoreView();
  $("themeSelect").addEventListener("change",e=>applyTheme(e.target.value));
  ["search","statusFilter","connectionFilter","apFilter"].forEach(id=>$(id).addEventListener("input",()=>{persistView();render();}));
  document.querySelectorAll("th[data-sort]").forEach(th=>th.addEventListener("click",()=>sortBy(th.dataset.sort)));
  $("refreshBtn").addEventListener("click",e=>{e.preventDefault();load();});
  $("autoRefreshSelect").value=localStorage.getItem("networkExplorerAutoRefresh")||"0";
  $("autoRefreshSelect").addEventListener("change",setupAutoRefresh);
  setupAutoRefresh();
  $("saveConfigBtn").addEventListener("click",e=>{e.preventDefault();saveConfig().catch(err=>setSetupMessage(err.message,"bad"));});
  $("generateKeyBtn").addEventListener("click",e=>{e.preventDefault();generateKey().catch(err=>setSetupMessage(err.message,"bad"));});
  $("installAllBtn").addEventListener("click",e=>{e.preventDefault();installAll().catch(err=>setSetupMessage(err.message,"bad"));});
  $("testSshBtn").addEventListener("click",e=>{e.preventDefault();testAll().catch(err=>setSetupMessage(err.message,"bad"));});
  $("addDeviceBtn").addEventListener("click",e=>{e.preventDefault();setupDevices.push(defaultDevice("Auto"));renderSetupDevices();});
  $("toggleSetupBtn").addEventListener("click",e=>{e.preventDefault();setSetupCollapsed(true);});
  $("settingsBtn").addEventListener("click",e=>{e.preventDefault();const hidden=$('setupPanel').classList.contains("collapsed");setSetupCollapsed(!hidden);if(hidden)$("setupPanel").scrollIntoView({behavior:"smooth",block:"start"});});
  setSetupCollapsed(localStorage.getItem("networkExplorerSetupCollapsed")==="1");
  loadConfig();
  load();
});
