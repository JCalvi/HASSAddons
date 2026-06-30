let rows=[], sortKey="ip", asc=true, expandedKey="";
let setupDevices=[];
let setupStatus={};
const $ = id => document.getElementById(id);
function addonBase(){
  const p = window.location.pathname || "/";
  return p.endsWith("/") ? p : p + "/";
}
function apiPath(path){
  return addonBase() + String(path||"").replace(/^\//, "");
}

function esc(s){return String(s||"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[m]));}
function ipVal(ip){return (ip||"999.999.999.999").split(".").map(x=>parseInt(x)||999);}
function cmp(a,b){if(sortKey==="ip"){let A=ipVal(a.ip),B=ipVal(b.ip);for(let i=0;i<4;i++)if(A[i]!==B[i])return A[i]-B[i];return 0;} if(sortKey==="rssi")return(parseInt(a.rssi)||-999)-(parseInt(b.rssi)||-999);return String(a[sortKey]||"").localeCompare(String(b[sortKey]||""));}
function sortBy(k){asc=sortKey===k?!asc:true;sortKey=k;render();}
function rssiClass(v){let n=parseInt(v);if(!n)return"";if(n>=-60)return"rssi-good";if(n>=-72)return"rssi-ok";return"rssi-bad";}
async function postJson(url,obj){const r=await fetch(apiPath(url),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(obj||{})});const d=await r.json();if(!d.ok)throw new Error(d.error||"Request failed");return d;}
function defaultDevice(type){return {type:type||"Host",name:"",ip:"",user:"root",password:"",ssh:"unknown",message:"",detail:""};}
function setSetupMessage(msg, kind="info"){$("setupStatus").className=`setup-status ${kind}`;$('setupStatus').textContent=msg||"";}
function setSetupOutput(obj){$("setupOutput").textContent=typeof obj==="string"?obj:JSON.stringify(obj,null,2);}
function showKeyInfo(key){if(!key){$("keyInfo").textContent="";return;}$("keyInfo").innerHTML=`<div><b>SSH key:</b> ${esc(key.exists?"created":"missing")} - ${esc(key.private_key||"")}</div><div><b>Public key:</b></div><code>${esc(key.public_key_text||"")}</code>`;}
function shortError(s){s=String(s||"").trim();if(!s)return"Failed";if(/Permission denied/i.test(s))return"Authentication failed";if(/Connection refused/i.test(s))return"Connection refused";if(/timed out|timeout/i.test(s))return"Connection timeout";if(/No route to host/i.test(s))return"No route to host";if(/Name or service not known|Could not resolve/i.test(s))return"Could not resolve host";return s.split("\n").map(x=>x.trim()).filter(Boolean).pop().slice(0,80)||"Failed";}
function deviceTypeClass(t){return (t||"Host").toLowerCase().replace(/[^a-z0-9]+/g,"-");}

function setupPayload(includePasswords=true){
  updateAllSetupDevices();
  return {
    devices: setupDevices.map(d=>({type:d.type,name:d.name,ip:d.ip,user:d.user,password:includePasswords?d.password:""})),
    piholes: setupDevices.filter(d=>d.type==="Pi-hole"&&d.ip).map(d=>d.ip),
    access_points: setupDevices.filter(d=>d.type==="OpenWrt AP"&&d.ip).map(d=>d.ip),
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
function updateAllSetupDevices(){setupDevices.forEach((_,i)=>updateDeviceFromRow(i));}
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
  if(total && ok===total){
    $("setupIntro").innerHTML=`<span class="ok-text">${ok} of ${total} devices configured.</span>`;
    $("toggleSetupBtn").textContent="Manage Devices";
  }else{
    $("setupIntro").textContent="Each device can use its own username and one-time password. Passwords are not saved.";
    $("toggleSetupBtn").textContent=$("setupPanel").classList.contains("collapsed")?"Show":"Hide";
  }
}
function renderSetupDevices(){
  $("setupDevices").innerHTML=setupDevices.map((d,i)=>{
    const installed=d.ssh==="ok";
    const detail=d.detail||d.message||"";
    return `<tr data-setup-index="${i}">
      <td><select class="dev-type type-${deviceTypeClass(d.type)}"><option ${d.type==="Pi-hole"?"selected":""}>Pi-hole</option><option ${d.type==="OpenWrt AP"?"selected":""}>OpenWrt AP</option><option ${d.type==="Host"?"selected":""}>Host</option></select></td>
      <td><input class="dev-name" value="${esc(d.name)}" placeholder="auto"></td>
      <td><input class="dev-ip" value="${esc(d.ip)}" placeholder="192.168.1.x"></td>
      <td><input class="dev-user" value="${esc(d.user||"root")}" placeholder="root"></td>
      <td><input class="dev-password" type="password" value="${esc(d.password||"")}" placeholder="${installed?"installed":"not saved"}" ${installed?"disabled":""}></td>
      <td class="ssh-status">${statusChip(d)}${d.ssh==="fail"&&detail?`<button class="link-button show-detail" type="button">Details</button>`:""}</td>
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
    d.message=d.ssh==="ok"?(r.host||"Connected"):shortError(r.error||"Failed");
    d.detail=r.error||r.host||"";
    if(r.host && !d.name)d.name=r.host;
    if(r.type)d.type=r.type;
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
      (c.access_points||[]).forEach(ip=>setupDevices.push({...defaultDevice("OpenWrt AP"),ip}));
    }
    renderSetupDevices(); showKeyInfo(d.key); testAll(false).catch(()=>{});
  }catch(e){setSetupMessage("Config load failed: "+e.message,"bad");}
}
async function saveConfig(show=true){
  const d=await postJson("api/config",setupPayload(false));
  showKeyInfo(d.key); if(show){setSetupMessage("Configuration saved.","ok");setSetupOutput(d.config||{});} return d;
}
async function generateKey(){
  await saveConfig(false); setSetupMessage("Generating SSH key...","info");
  const d=await postJson("api/ssh/generate",{}); showKeyInfo(d.key); setSetupMessage("SSH key ready.","ok"); setSetupOutput(d.key||{}); return d;
}
async function installOne(i){
  updateDeviceFromRow(i); const dev=setupDevices[i];
  if(!dev.ip){setSetupMessage("IP address required.","bad");return;}
  if(!dev.password){setSetupMessage(`Password required for ${dev.ip}.`,"bad");return;}
  dev.ssh="installing";dev.message="Installing key";dev.detail="";renderSetupDevices();
  const payload=setupPayload(true); payload.ip=dev.ip;
  const d=await postJson("api/ssh/install_one",payload); mergeStatuses(d.results); showKeyInfo(d.key); setSetupOutput(d.results||[]);
  const r=(d.results||[]).find(x=>x.ip===dev.ip);
  setSetupMessage(r&&r.ok?`SSH key installed on ${dev.ip}.`:`Install failed for ${dev.ip}.`,r&&r.ok?"ok":"bad");
}
async function installAll(){
  updateAllSetupDevices(); setSetupMessage("Installing SSH keys...","info");
  setupDevices.forEach(d=>{if(d.ip&&d.password){d.ssh="installing";d.message="Installing key";}});renderSetupDevices();
  const d=await postJson("api/ssh/install_all",setupPayload(true)); mergeStatuses(d.results); showKeyInfo(d.key); setSetupOutput(d.results||[]);
  const ok=(d.results||[]).filter(x=>x.ok&&x.key_ok!==false).length; const total=(d.results||[]).length;
  setSetupMessage(`${ok} of ${total} SSH keys installed/tested successfully.`,ok===total?"ok":"bad");
}
async function testOne(i){
  updateDeviceFromRow(i); const dev=setupDevices[i];
  if(!dev.ip){setSetupMessage("IP address required.","bad");return;}
  dev.ssh="testing";dev.message="Testing";dev.detail="";renderSetupDevices();
  const payload=setupPayload(false); payload.devices=[{type:dev.type,name:dev.name,ip:dev.ip,user:dev.user,password:""}];
  const d=await postJson("api/ssh/test",payload); mergeStatuses(d.results); setSetupOutput(d.results||[]);
  const r=(d.results||[]).find(x=>x.ip===dev.ip);
  setSetupMessage(r&&r.ok?`${dev.ip} connected.`:`${dev.ip} failed: ${shortError(r&&r.error)}`,r&&r.ok?"ok":"bad");
}
async function testAll(show=true){
  updateAllSetupDevices(); if(show)setSetupMessage("Testing SSH connections...","info");
  setupDevices.forEach(d=>{if(d.ip){d.ssh="testing";d.message="Testing";}});renderSetupDevices();
  const d=await postJson("api/ssh/test",setupPayload(false)); mergeStatuses(d.results); setSetupOutput(d.results||[]);
  const ok=(d.results||[]).filter(x=>x.ok).length; const total=(d.results||[]).length;
  if(show)setSetupMessage(`${ok} of ${total} SSH connections OK.`,ok===total?"ok":"bad");
}

function fillFilters(){
  const conns=[...new Set(rows.map(x=>x.connection).filter(Boolean))].sort(); const aps=[...new Set(rows.map(x=>x.ap).filter(Boolean))].sort();
  const c=$("connectionFilter"), a=$("apFilter"); const cv=c.value, av=a.value;
  c.innerHTML='<option value="">All connections</option>'+conns.map(x=>`<option>${esc(x)}</option>`).join("");
  a.innerHTML='<option value="">All APs</option>'+aps.map(x=>`<option>${esc(x)}</option>`).join("");
  c.value=cv; a.value=av;
}
function statusText(x){return x.status==="online"?"Online":x.status==="idle"?"Idle":"Offline";}
function detailHtml(x){return `<tr class="detail"><td colspan="9"><b>${esc(x.host||x.ip||x.mac||"Unknown device")}</b><div class="detail-grid"><div>IP</div><div>${esc(x.ip)}</div><div>Host</div><div>${esc(x.host)}</div><div>MAC</div><div>${esc(x.mac)}</div><div>Status</div><div>${esc(statusText(x))}</div><div>Connection</div><div>${esc(x.connection)}</div><div>AP</div><div>${esc(x.ap)}</div><div>Band</div><div>${esc(x.band)}</div><div>RSSI</div><div>${esc(x.rssi?x.rssi+" dBm":"")}</div><div>Ping</div><div>${esc(x.ping)}</div><div>TCP</div><div>${esc(x.tcp)}</div><div>Neighbour State</div><div>${esc(x.neighbour_state)}</div><div>Last Wi-Fi Event</div><div>${esc(x.wifi_last_event)}</div><div>Last Wi-Fi Seen</div><div>${esc(x.wifi_last_seen)}</div><div>Source</div><div>${esc(x.source)}</div></div></td></tr>`;}
function render(){
  let q=$("search").value.toLowerCase(), status=$("statusFilter").value, conn=$("connectionFilter").value, ap=$("apFilter").value;
  let out=rows.filter(x=>{let blob=Object.values(x).join(" ").toLowerCase();if(q&&!blob.includes(q))return false;if(status&&x.status!==status)return false;if(conn&&x.connection!==conn)return false;if(ap&&x.ap!==ap)return false;return true;}).sort((a,b)=>asc?cmp(a,b):-cmp(a,b));
  $("body").innerHTML=out.map(x=>{const key=`${x.ip}|${x.mac}`;const open=expandedKey===key;return `<tr class="mainrow" data-key="${esc(key)}"><td>${esc(x.ip)}</td><td>${esc(x.host)}</td><td>${esc(x.mac)}</td><td><span class="status-pill ${esc(x.status)}">${esc(statusText(x))}</span></td><td>${esc(x.connection)}</td><td>${esc(x.ap)}</td><td>${esc(x.band)}</td><td class="${rssiClass(x.rssi)}">${esc(x.rssi)}</td><td>${esc(x.source)}</td></tr>${open?detailHtml(x):""}`;}).join("");
  document.querySelectorAll(".mainrow").forEach(row=>row.addEventListener("click",()=>{expandedKey=expandedKey===row.dataset.key?"":row.dataset.key;render();}));
  const online=rows.filter(x=>x.status==="online").length, idle=rows.filter(x=>x.status==="idle").length, offline=rows.filter(x=>x.status==="offline").length;
  const wifi=rows.filter(x=>x.status==="online"&&x.connection&&x.connection!=="Ethernet"&&x.connection!=="Tailscale").length;
  const wired=rows.filter(x=>x.status==="online"&&x.connection==="Ethernet").length;
  const tailscale=rows.filter(x=>x.status==="online"&&x.connection==="Tailscale").length;
  $("updated").textContent=`Updated ${new Date().toLocaleTimeString()} - ${out.length}/${rows.length} shown`;
  $("summary").innerHTML=`<span>${rows.length} devices</span><span>${online} online</span><span>${idle} idle</span><span>${offline} offline</span><span>Wi-Fi ${wifi}</span><span>Ethernet ${wired}</span><span>Tailscale ${tailscale}</span>`;
}
async function load(){const btn=$("refreshBtn"); btn.disabled=true; btn.textContent="Refreshing..."; $("updated").textContent="Refreshing..."; try{const r=await fetch(apiPath("api/refresh?_="+Date.now()),{cache:"no-store"}); const data=await r.json(); if(!data.ok) throw new Error(data.error||"Refresh failed"); rows=data.devices||[]; fillFilters(); render();}catch(e){$("updated").textContent="Refresh failed: "+e.message;} btn.disabled=false; btn.textContent="Refresh";}
function setSetupCollapsed(collapsed){const p=$("setupPanel");p.classList.toggle("collapsed", collapsed);$("toggleSetupBtn").textContent=collapsed?"Show":"Hide";localStorage.setItem("networkExplorerSetupCollapsed", collapsed?"1":"0");renderSetupSummary();}
function applyTheme(theme){document.documentElement.dataset.theme=theme;localStorage.setItem("networkExplorerTheme",theme);$("themeSelect").value=theme;}

document.addEventListener("DOMContentLoaded",()=>{
  applyTheme(localStorage.getItem("networkExplorerTheme")||"auto");
  $("themeSelect").addEventListener("change",e=>applyTheme(e.target.value));
  ["search","statusFilter","connectionFilter","apFilter"].forEach(id=>$(id).addEventListener("input",render));
  document.querySelectorAll("th[data-sort]").forEach(th=>th.addEventListener("click",()=>sortBy(th.dataset.sort)));
  $("refreshBtn").addEventListener("click",e=>{e.preventDefault();load();});
  $("saveConfigBtn").addEventListener("click",e=>{e.preventDefault();saveConfig().catch(err=>setSetupMessage(err.message,"bad"));});
  $("generateKeyBtn").addEventListener("click",e=>{e.preventDefault();generateKey().catch(err=>setSetupMessage(err.message,"bad"));});
  $("installAllBtn").addEventListener("click",e=>{e.preventDefault();installAll().catch(err=>setSetupMessage(err.message,"bad"));});
  $("testSshBtn").addEventListener("click",e=>{e.preventDefault();testAll().catch(err=>setSetupMessage(err.message,"bad"));});
  $("addPiholeBtn").addEventListener("click",e=>{e.preventDefault();setupDevices.push(defaultDevice("Pi-hole"));renderSetupDevices();});
  $("addApBtn").addEventListener("click",e=>{e.preventDefault();setupDevices.push(defaultDevice("OpenWrt AP"));renderSetupDevices();});
  $("toggleSetupBtn").addEventListener("click",e=>{e.preventDefault();setSetupCollapsed(!$('setupPanel').classList.contains("collapsed"));});
  $("settingsBtn").addEventListener("click",e=>{e.preventDefault();setSetupCollapsed(false);$("setupPanel").scrollIntoView({behavior:"smooth",block:"start"});});
  setSetupCollapsed(localStorage.getItem("networkExplorerSetupCollapsed")==="1");
  loadConfig();
  load();
});
