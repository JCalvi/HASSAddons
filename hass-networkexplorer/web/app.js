let rows=[], sortKey="ip", asc=true, expandedKey="";
const $ = id => document.getElementById(id);

function esc(s){return String(s||"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[m]));}
function ipVal(ip){return (ip||"999.999.999.999").split(".").map(x=>parseInt(x)||999);}
function cmp(a,b){if(sortKey==="ip"){let A=ipVal(a.ip),B=ipVal(b.ip);for(let i=0;i<4;i++)if(A[i]!==B[i])return A[i]-B[i];return 0;} if(sortKey==="rssi")return(parseInt(a.rssi)||-999)-(parseInt(b.rssi)||-999);return String(a[sortKey]||"").localeCompare(String(b[sortKey]||""));}
function sortBy(k){asc=sortKey===k?!asc:true;sortKey=k;render();}
function rssiClass(v){let n=parseInt(v);if(!n)return"";if(n>=-60)return"rssi-good";if(n>=-72)return"rssi-ok";return"rssi-bad";}

function fillFilters(){
  const conns=[...new Set(rows.map(x=>x.connection).filter(Boolean))].sort();
  const aps=[...new Set(rows.map(x=>x.ap).filter(Boolean))].sort();
  const c=$("connectionFilter"), a=$("apFilter"), cv=c.value, av=a.value;
  c.innerHTML='<option value="">All connections</option>'+conns.map(x=>`<option>${esc(x)}</option>`).join("");
  a.innerHTML='<option value="">All APs</option>'+aps.map(x=>`<option>${esc(x)}</option>`).join("");
  c.value=cv; a.value=av;
}

function detailHtml(x){return `<tr class="detail"><td colspan="9"><b>${esc(x.host||x.ip||x.mac||"Unknown device")}</b><div class="detail-grid">
<div>IP</div><div>${esc(x.ip)}</div><div>Host</div><div>${esc(x.host)}</div><div>MAC</div><div>${esc(x.mac)}</div><div>Status</div><div>${esc(x.status)}</div><div>Connection</div><div>${esc(x.connection)}</div><div>AP</div><div>${esc(x.ap)}</div><div>Band</div><div>${esc(x.band)}</div><div>RSSI</div><div>${esc(x.rssi?x.rssi+" dBm":"")}</div><div>Ping</div><div>${esc(x.ping)}</div><div>TCP</div><div>${esc(x.tcp)}</div><div>Neighbour State</div><div>${esc(x.neighbour_state)}</div><div>Last Wi-Fi Event</div><div>${esc(x.wifi_last_event)}</div><div>Last Wi-Fi Seen</div><div>${esc(x.wifi_last_seen)}</div><div>Source</div><div>${esc(x.source)}</div>
</div></td></tr>`;}

function render(){
  let q=$("search").value.toLowerCase(), status=$("statusFilter").value, conn=$("connectionFilter").value, ap=$("apFilter").value;
  let out=rows.filter(x=>{let blob=Object.values(x).join(" ").toLowerCase();if(q&&!blob.includes(q))return false;if(status&&x.status!==status)return false;if(conn&&x.connection!==conn)return false;if(ap&&x.ap!==ap)return false;return true;}).sort((a,b)=>asc?cmp(a,b):-cmp(a,b));
  $("body").innerHTML=out.map(x=>{const key=`${x.ip}|${x.mac}`;const open=expandedKey===key;return `<tr class="mainrow" data-key="${esc(key)}"><td>${esc(x.ip)}</td><td>${esc(x.host)}</td><td>${esc(x.mac)}</td><td class="${esc(x.status)}">${esc(x.status)}</td><td>${esc(x.connection)}</td><td>${esc(x.ap)}</td><td>${esc(x.band)}</td><td class="${rssiClass(x.rssi)}">${esc(x.rssi)}</td><td>${esc(x.source)}</td></tr>${open?detailHtml(x):""}`;}).join("");
  document.querySelectorAll(".mainrow").forEach(row=>row.addEventListener("click",()=>{expandedKey=expandedKey===row.dataset.key?"":row.dataset.key;render();}));
  const online=rows.filter(x=>x.status==="online").length, idle=rows.filter(x=>x.status==="idle").length, offline=rows.filter(x=>x.status==="offline").length;
  const wifi=rows.filter(x=>x.status==="online"&&x.connection&&x.connection!=="Ethernet"&&x.connection!=="Tailscale").length;
  const wired=rows.filter(x=>x.status==="online"&&x.connection==="Ethernet").length;
  const tailscale=rows.filter(x=>x.status==="online"&&x.connection==="Tailscale").length;
  $("updated").textContent=`Updated ${new Date().toLocaleTimeString()} - ${out.length}/${rows.length} shown`;
  $("summary").textContent=`${rows.length} devices - ${online} online - ${idle} idle - ${offline} offline - Wi-Fi ${wifi} - Ethernet ${wired} - Tailscale ${tailscale}`;
}

async function load(){
  const btn=$("refreshBtn"); btn.disabled=true; btn.textContent="Refreshing..."; $("updated").textContent="Refreshing...";
  try{const r=await fetch("/api/refresh?_="+Date.now(),{cache:"no-store"}); const data=await r.json(); if(!data.ok) throw new Error(data.error||"Refresh failed"); rows=data.devices||[]; fillFilters(); render();}
  catch(e){$("updated").textContent="Refresh failed: "+e.message;}
  btn.disabled=false; btn.textContent="Refresh";
}

document.addEventListener("DOMContentLoaded",()=>{["search","statusFilter","connectionFilter","apFilter"].forEach(id=>$(id).addEventListener("input",render));document.querySelectorAll("th[data-sort]").forEach(th=>th.addEventListener("click",()=>sortBy(th.dataset.sort)));$("refreshBtn").addEventListener("click",e=>{e.preventDefault();load();});load();});
