const __vite__mapDeps=(i,m=__vite__mapDeps,d=(m.f||(m.f=["assets/rfb-SqJWBMob.js","assets/vendor-novnc-MJ7Ztc8T.js"])))=>i.map(i=>d[i]);
import{A as e,B as t,F as n,N as r,O as i,P as a,U as o,b as s,j as c,k as l,o as u,r as d,y as f}from"./dock-Cs1V2j2B.js";import{r as p}from"./app-i18n-DNpVdZEW.js";var m=null,h=[],g=null,_=[],v=[`br0`];function y(){if(window._vmManagerInitialized)return;window._vmManagerInitialized=!0;let e=document.getElementById(`vm-desktop-icon`),t=e=>{if(e&&e.type===`touchend`&&e.preventDefault(),window.DockManager){if(!window.DockManager.windows.vm){let e=document.getElementById(`vm-manager-window`);e&&window.DockManager.register(`vm`,e,`#i-vm`,p(`dock.vm_manager`,`Virtual Machines`))}window.DockManager.restore(`vm`)}o.emit(`window:open`,{id:`vm-manager-window`}),b()};if(e&&(e.addEventListener(`click`,t),e.addEventListener(`touchend`,t),e.addEventListener(`dblclick`,t),e.addEventListener(`keydown`,e=>{(e.key===`Enter`||e.key===` `)&&(e.preventDefault(),t())})),window.openVmManager=t,!document.getElementById(`vm-manager-window`)){let e=`
      <div id="vm-manager-window" class="os-window vm-manager-window" style="display: none; width: 920px; height: 600px; min-width: 640px; min-height: 420px;">
        <div class="os-window-header">
          <div class="os-window-title">
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
            <span data-i18n="dock.vm_manager">${p(`dock.vm_manager`,`Virtual Machines`)}</span>
          </div>
          <div class="os-window-controls">
            <button class="win-btn min-btn" id="vm-min" title="Minimize" aria-label="Minimize"></button>
            <button class="win-btn max-btn" id="vm-max" title="Maximize" aria-label="Maximize"></button>
            <button class="win-btn close-btn" id="vm-close" title="Close" aria-label="Close"></button>
          </div>
        </div>

        <!-- Telemetry & Headroom Summary Header -->
        <div id="vm-telemetry-header" class="vm-telemetry-header" style="display: flex; flex-direction: column; gap: 10px; padding: 16px; background: rgba(0,0,0,0.25); border-bottom: 1px solid rgba(255,255,255,0.06);">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
            <div id="vm-kvm-badge" style="display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.3);">
              <span>⚡</span> <span>Loading KVM Status...</span>
            </div>
            <div class="vm-action-btns-wrap" style="display: flex; gap: 8px;">
              <button id="btn-vm-refresh" class="btn-pill-toggle" title="${p(`vm.refresh`,`Refresh`)}" style="display: inline-flex; align-items: center; gap: 6px;">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
                <span data-i18n="vm.refresh">${p(`vm.refresh`,`Refresh`)}</span>
              </button>
              <button id="btn-vm-isos" class="btn-pill-toggle" title="ISO Library & Official Catalog" style="display: inline-flex; align-items: center; gap: 6px;">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/><line x1="12" y1="2" x2="12" y2="5"/></svg>
                <span>ISO Library</span>
              </button>
              <button id="btn-vm-create" class="btn-save-preset" style="background: var(--accent-cyan, #0ea5e9); border-color: rgba(14, 165, 233, 0.4); color: #fff; font-weight: 700;">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                <span data-i18n="vm.create_btn">${r(p(`vm.create_btn`,`Create Virtual Machine`))}</span>
              </button>
            </div>
          </div>

          <div class="vm-telemetry-budget-grid" style="display: grid; grid-template-columns: 1.5fr 1fr; gap: 14px;">
            <!-- Memory Budget Card -->
            <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.05); border-radius: 8px; padding: 10px 14px;">
              <div style="display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 6px;">
                <span style="color: var(--muted); font-weight: 600;" data-i18n="vm.host_reserve">${p(`vm.host_reserve`,`Host Memory Reserve`)} (10% Dynamic)</span>
                <span id="vm-headroom-text" style="color: #38bdf8; font-weight: 700;">--</span>
              </div>
              <div style="height: 10px; border-radius: 5px; background: rgba(255,255,255,0.08); overflow: hidden; display: flex;" id="vm-memory-segments">
                <div id="vm-seg-running" style="width: 0%; background: #0ea5e9; transition: width 0.3s;" title="Running VMs"></div>
                <div id="vm-seg-reserve" style="width: 10%; background: #f59e0b; transition: width 0.3s;" title="Host Reserve (Protected)"></div>
                <div id="vm-seg-headroom" style="width: 0%; background: #10b981; transition: width 0.3s;" title="Available Safe Headroom"></div>
              </div>
              <div style="display: flex; justify-content: space-between; font-size: 10px; color: var(--muted); margin-top: 6px;">
                <span>Total Host: <strong id="vm-total-ram" style="color:#fff;">--</strong></span>
                <span>Safe Ceiling: <strong id="vm-safe-ceiling" style="color:#34d399;">--</strong></span>
              </div>
            </div>

            <!-- CPU Thread Overcommit Card -->
            <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.05); border-radius: 8px; padding: 10px 14px;">
              <div style="display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 6px;">
                <span style="color: var(--muted); font-weight: 600;">vCPU Thread Allocation</span>
                <span id="vm-cpu-ratio-badge" style="font-size: 10px; padding: 1px 6px; border-radius: 4px; background: rgba(16,185,129,0.2); color: #34d399;">1:1 Physical</span>
              </div>
              <div style="display: flex; align-items: baseline; gap: 8px; margin-top: 4px;">
                <span style="font-size: 18px; font-weight: 700; color: #fff;" id="vm-cpu-allocated">0</span>
                <span style="font-size: 11px; color: var(--muted);">/ <span id="vm-cpu-threads">8</span> Host Threads</span>
              </div>
              <div style="font-size: 10px; color: var(--muted); margin-top: 6px;" id="vm-cpu-note">Optimal execution. Dedicated physical thread capacity per vCPU.</div>
            </div>
          </div>
        </div>

        <!-- VM Inventory Content -->
        <div class="vm-content-body" data-scrollable="true" style="flex: 1; min-height: 0; overflow-y: auto; -webkit-overflow-scrolling: touch; touch-action: pan-y; padding: 16px;">
          <div id="vm-empty-state" style="display: none; text-align: center; padding: 48px 24px; color: var(--muted); font-size: 13px;">
            <div style="margin-bottom: 12px; color: var(--muted); opacity: 0.6;">
              <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
            </div>
            <div data-i18n="vm.no_vms" style="font-weight: 600; color: #94a3b8; margin-bottom: 14px;">${p(`vm.no_vms`,`No virtual machines configured yet.`)}</div>
            <button id="btn-vm-empty-create" class="btn-save-preset" style="background: var(--accent-cyan, #0ea5e9); border-color: rgba(14, 165, 233, 0.4); color: #fff; margin: 0 auto;">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              <span data-i18n="vm.create_btn">${r(p(`vm.create_btn`,`Create Virtual Machine`))}</span>
            </button>
          </div>
          <div id="vm-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px;"></div>
        </div>
      </div>
    `;document.body.insertAdjacentHTML(`beforeend`,e)}m=document.getElementById(`vm-manager-window`);let n=document.getElementById(`vm-min`),i=document.getElementById(`vm-max`),a=document.getElementById(`vm-close`);n&&(n.onclick=e=>{e&&(e.preventDefault(),e.stopPropagation()),m&&(m.classList.add(`window-minimized`),m.classList.remove(`open`),m.style.setProperty(`display`,`none`,`important`)),window.DockManager&&window.DockManager.minimize(`vm`)}),a&&(a.onclick=e=>{e&&(e.preventDefault(),e.stopPropagation()),m&&(m.classList.add(`window-minimized`),m.classList.remove(`open`),m.style.setProperty(`display`,`none`,`important`)),window.DockManager&&window.DockManager.closeWindow(`vm`)});let s=!1,c=null;i&&(i.onclick=()=>{s?(c&&(m.style.left=c.left,m.style.top=c.top,m.style.width=c.width,m.style.height=c.height),s=!1):(c={left:m.style.left,top:m.style.top,width:m.style.width,height:m.style.height},m.style.left=`0px`,m.style.top=`36px`,m.style.width=`100vw`,m.style.height=`calc(100vh - 36px - 72px)`,s=!0)});let l=document.getElementById(`btn-vm-create`);l&&(l.onclick=()=>N());let f=document.getElementById(`btn-vm-isos`);f&&(f.onclick=()=>ue(`catalog`));let h=document.getElementById(`btn-vm-empty-create`);h&&(h.onclick=()=>N());let g=document.getElementById(`btn-vm-refresh`);g&&(g.onclick=()=>b()),m&&(u(m,m.querySelector(`.os-window-header`)),m.addEventListener(`mousedown`,()=>d(m)))}async function b(){try{let[e,n,r,i]=await Promise.all([t.get(`/api/vms/telemetry`),t.get(`/api/vms`),t.get(`/api/vms/isos`),t.get(`/api/vms/bridges`)]);g=e,h=n||[],_=r||[],v=i||[`br0`],S(e),E(h)}catch(e){c(`Failed to load VM data: ${e.message}`,`error`)}}function x(){return g?.kvm?.vtpm_available===!1?`<span class="vm-tpm-badge unavailable" title="${r(p(`vm.tpm_unavailable_hint`,`Install the swtpm package on the host (or update the container image) to use vTPM.`))}" style="font-size: 9px; padding: 2px 6px; border-radius: 4px; background: rgba(245,158,11,0.15); color: #fbbf24; border: 1px solid rgba(245,158,11,0.3);">⚠️ ${r(p(`vm.tpm_unavailable`,`swtpm not installed`))}</span>`:`<span class="vm-tpm-badge" style="font-size: 9px; padding: 2px 6px; border-radius: 4px; background: rgba(14,165,233,0.15); color: #38bdf8; border: 1px solid rgba(14,165,233,0.3);">🛡️ ${r(p(`vm.tpm_ready`,`Windows 11 Ready`))}</span>`}function S(e){if(!e)return;let t=document.getElementById(`vm-kvm-badge`);t&&e.kvm&&(t.innerHTML=`<span>⚡</span> <span>${r(e.kvm.badge||`KVM Active`)}</span> <span style="font-size: 10px; opacity: 0.8; margin-left: 2px;" title="View KVM Diagnostics & Fix">ℹ️</span>`,t.style.cursor=`pointer`,t.onclick=()=>M(e.kvm),e.kvm.state===`active`?(t.style.background=`rgba(16,185,129,0.15)`,t.style.color=`#34d399`,t.style.borderColor=`rgba(16,185,129,0.3)`):e.kvm.state===`restricted`?(t.style.background=`rgba(245,158,11,0.15)`,t.style.color=`#fbbf24`,t.style.borderColor=`rgba(245,158,11,0.3)`):(t.style.background=`rgba(239,68,68,0.15)`,t.style.color=`#f87171`,t.style.borderColor=`rgba(239,68,68,0.3)`));let n=e.memory_budget;if(n){let e=n.total_host_ram_gb||32,t=Math.min(100,Math.round(n.allocated_vm_ram_gb/e*100)),r=Math.min(100,Math.round(n.host_reserve_gb/e*100)),i=Math.max(0,100-t-r),a=document.getElementById(`vm-seg-running`),o=document.getElementById(`vm-seg-reserve`),s=document.getElementById(`vm-seg-headroom`);a&&(a.style.width=`${t}%`),o&&(o.style.width=`${r}%`),s&&(s.style.width=`${i}%`);let c=document.getElementById(`vm-headroom-text`);c&&(c.textContent=`${n.safe_headroom_gb} GB Safe Headroom (${n.allocated_vm_ram_gb} GB in use)`);let l=document.getElementById(`vm-total-ram`);l&&(l.textContent=`${n.total_host_ram_gb} GB`);let u=document.getElementById(`vm-safe-ceiling`);u&&(u.textContent=`${n.safe_max_vm_ram_gb} GB`)}let i=e.cpu_capacity;if(i){let e=document.getElementById(`vm-cpu-allocated`),t=document.getElementById(`vm-cpu-threads`),n=document.getElementById(`vm-cpu-ratio-badge`),r=document.getElementById(`vm-cpu-note`);e&&(e.textContent=i.allocated_vcpus),t&&(t.textContent=i.host_threads),n&&(n.textContent=i.badge||`${i.overcommit_ratio}x`,i.status===`nominal`?(n.style.background=`rgba(16,185,129,0.2)`,n.style.color=`#34d399`,r&&(r.textContent=`Optimal execution. Dedicated physical thread capacity per vCPU.`)):i.status===`moderate_overcommit`?(n.style.background=`rgba(245,158,11,0.2)`,n.style.color=`#fbbf24`,r&&(r.textContent=`Moderate overcommit. Bursty workloads normal; concurrent spikes may queue.`)):(n.style.background=`rgba(239,68,68,0.2)`,n.style.color=`#f87171`,r&&(r.textContent=`High thread contention risk. Advised only for idle background appliances.`)))}}function C(e,t){return[t.findIndex(t=>t.id===e.id),e.state,e.qemu_pid,e.name,e.description,e.os_family,e.boot_order,e.iso_path,e.ip_address,e.vcpus,e.ram_gb,e.disk_size_gb,e.disk_format,e.bridge,e.vnc_port,e.ssh_port].join(`|`)}function w(e){let t=document.createElement(`template`);return t.innerHTML=e.trim(),t.content.firstElementChild}function T(e,t){let n=t.cpu_usage_pct===void 0?0:t.cpu_usage_pct,r=t.ram_usage_pct===void 0?0:t.ram_usage_pct,i=(parseFloat(t.ram_gb||2)*(parseFloat(r)/100)).toFixed(1),a=e.querySelectorAll(`.vm-telemetry-row .telemetry-val`);a[0]&&(a[0].textContent=`${n}%`),a[1]&&(a[1].textContent=`${i} / ${t.ram_gb} GB`);let o=e.querySelector(`.vm-telemetry-row .fill-cpu`);o&&(o.style.width=`${Math.min(100,Math.round(parseFloat(n)*4))}%`);let s=e.querySelector(`.vm-telemetry-row .fill-ram`);s&&(s.style.width=`${Math.min(100,Math.round(r))}%`)}function E(e){let t=document.getElementById(`vm-grid`),n=document.getElementById(`vm-empty-state`);if(!t)return;if(!e||e.length===0){t.innerHTML=``,n&&(n.style.display=`block`);return}n&&(n.style.display=`none`);let r=!1;a(t,e,e=>e.id,t=>{let n=w(D(t,e));return n.dataset.structKey=C(t,e),r=!0,n},(t,n)=>{let i=C(n,e);if(t.dataset.structKey===i){T(t,n);return}let a=w(D(n,e));t.innerHTML=a.innerHTML;for(let{name:e,value:n}of Array.from(a.attributes))t.setAttribute(e,n);t.dataset.structKey=i,r=!0}),r&&O(t)}function D(e,t){let n=`${e.state}|${e.qemu_pid}|${e.cpu_usage_pct}|${e.ram_usage_pct}|${e.ip_address}|${e.vcpus}|${e.ram_gb}|${e.disk_size_gb}|${e.name}`,i=e.state===`running`,a=e.state===`paused`,o=`<span style="padding: 2px 7px; border-radius: 4px; font-size: 10px; font-weight: 700; background: ${i?`rgba(16,185,129,0.15)`:a?`rgba(245,158,11,0.15)`:`rgba(255,255,255,0.06)`}; color: ${i?`#34d399`:a?`#fbbf24`:`#94a3b8`}; text-transform: uppercase;">${e.state}</span>`,s=e.vnc_port||5901+t.findIndex(t=>t.id===e.id)%10,c=Math.max(1,s-5900),l=e.ssh_port||2220+c,u=typeof window<`u`&&window.location&&window.location.hostname||`localhost`,d=e.ip_address?`ssh root@${e.ip_address}`:`ssh -p ${l} root@${u}`,f=`vnc://${u}:${s}`,m=e.qemu_pid||null,h=e.boot_order||(e.iso_path?`iso`:`disk`),g=e.cpu_usage_pct===void 0?0:e.cpu_usage_pct,_=e.ram_usage_pct===void 0?0:e.ram_usage_pct,v=(parseFloat(e.ram_gb||2)*(parseFloat(_)/100)).toFixed(1),y=e.os_family===`windows`?`<svg width="18" height="18" viewBox="0 0 24 24" fill="#38bdf8" style="flex-shrink: 0;"><path d="M0 3.449L9.75 2.1v9.451H0m10.949-9.602L24 0v11.4H10.949M0 12.6h9.75v9.451L0 20.699M10.949 12.6H24V24l-12.949-1.801"/></svg>`:e.os_family===`linux`?`<svg width="18" height="18" viewBox="0 0 24 24" fill="#fbbf24" style="flex-shrink: 0;"><path d="M12 2a5 5 0 0 0-5 5v3.1c-1.3.8-2 2-2 3.9 0 2.2 1.3 4 3 4.8V20a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2v-1.2c1.7-.8 3-2.6 3-4.8 0-1.9-.7-3.1-2-3.9V7a5 5 0 0 0-5-5zm-2 6a1 1 0 1 1 0-2 1 1 0 0 1 0 2zm4 0a1 1 0 1 1 0-2 1 1 0 0 1 0 2z"/></svg>`:`<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2" style="flex-shrink: 0;"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>`;return`
      <div class="glassmorphic-card" data-vm-id="${r(e.id)}" data-state-key="${r(n)}" style="border-radius: 10px; padding: 14px; display: flex; flex-direction: column; justify-content: space-between; border: 1px solid rgba(255,255,255,0.08); background: rgba(18, 26, 38, 0.65);">
        <div>
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              ${y}
              <div>
                <div style="font-weight: 700; color: #fff; font-size: 13px;">${r(e.name)}</div>
                <div style="font-size: 10px; color: var(--muted);">${r(e.description||`Virtual Appliance`)}</div>
              </div>
            </div>
            <div style="display: flex; align-items: center; gap: 5px; flex-wrap: wrap; justify-content: flex-end;">
              ${h===`disk`?`<span class="vm-boot-order-pill disk" title="Boot order: Virtual disk first">💽 Disk</span>`:`<span class="vm-boot-order-pill iso" title="Boot order: ISO installer first">💿 ISO First</span>`}
              ${i?`<span class="qemu-process-badge active" title="QEMU KVM hypervisor process active">● QEMU ${m?`(${m})`:`Active`}</span>`:a?`<span class="qemu-process-badge paused" title="QEMU process paused">⏸ QEMU Paused</span>`:`<span class="qemu-process-badge stopped" title="QEMU process inactive">○ QEMU Stopped</span>`}
              ${o}
            </div>
          </div>

          <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; font-size: 11px; margin: 12px 0 8px; background: rgba(0,0,0,0.3); padding: 8px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.04);">
            <div><span style="color: var(--muted);">${p(`vm.compute`,`Compute`)}:</span> <strong style="color: #fff;">${e.vcpus} vCPUs</strong></div>
            <div><span style="color: var(--muted);">${p(`vm.memory`,`Memory`)}:</span> <strong style="color: #38bdf8;">${e.ram_gb} GB</strong></div>
            <div><span style="color: var(--muted);">${p(`vm.disk`,`Disk`)}:</span> <strong style="color: #fff;">${e.disk_size_gb} GB (${e.disk_format})</strong></div>
            <div><span style="color: var(--muted);">${p(`vm.bridge`,`Bridge`)}:</span> <strong style="color: #fff;">${r(e.bridge||`br0`)}</strong></div>
          </div>

          <!-- Real-time Live Resource Telemetry -->
          ${i?`
            <div class="vm-telemetry-row">
              <div class="vm-telemetry-item">
                <div class="vm-telemetry-header">
                  <span>vCPU Load</span>
                  <span class="telemetry-val">${g}%</span>
                </div>
                <div class="vm-telemetry-progress"><div class="fill-cpu" style="width: ${Math.min(100,Math.round(parseFloat(g)*4))}%;"></div></div>
              </div>
              <div class="vm-telemetry-item">
                <div class="vm-telemetry-header">
                  <span>RAM Used</span>
                  <span class="telemetry-val">${v} / ${e.ram_gb} GB</span>
                </div>
                <div class="vm-telemetry-progress"><div class="fill-ram" style="width: ${Math.min(100,Math.round(_))}%;"></div></div>
              </div>
            </div>
          `:``}

          <!-- Connection Info Bar with 1-Click Copy Buttons -->
          <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; padding: 4px 8px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; margin-bottom: 8px;">
            <div style="display: flex; align-items: center; gap: 6px; font-family: monospace; font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
              <span style="color: #f59e0b; display: inline-flex; align-items: center; gap: 3px;">
                <span>VNC :${c}</span>
                <button class="btn-copy-vnc" data-uri="${r(f)}" style="background: none; border: none; cursor: pointer; color: var(--muted); padding: 1px 3px; display: inline-flex; align-items: center;" title="Copy VNC URI (${f})">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                </button>
              </span>
              <span style="color: rgba(255,255,255,0.15);">|</span>
              <span style="color: #38bdf8; display: inline-flex; align-items: center; gap: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                <span>${r(d)}</span>
                <button class="btn-copy-ssh-cmd" data-cmd="${r(d)}" style="background: none; border: none; cursor: pointer; color: var(--muted); padding: 1px 3px; display: inline-flex; align-items: center;" title="Copy SSH Command">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                </button>
              </span>
            </div>
            <button class="btn-vm-join-toggle" data-id="${e.id}" style="background: rgba(14,165,233,0.15); border: 1px solid rgba(14,165,233,0.3); border-radius: 4px; color: #38bdf8; font-size: 10px; font-weight: 700; padding: 2px 6px; cursor: pointer; flex-shrink: 0;" title="Join VM connection options">
              Join ▾
            </button>
          </div>

          ${e.iso_path?`
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; padding: 6px 10px; background: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.3); border-radius: 4px; margin-bottom: 10px;">
              <span style="color: #fbbf24; font-weight: 600; display: flex; align-items: center; gap: 6px;">
                <span>💿</span>
                <span>ISO Attached (${r(e.iso_path.split(`/`).pop())})</span>
              </span>
              <div style="display: flex; gap: 4px;">
                <button class="btn-join-gui" data-id="${e.id}" data-name="${r(e.name)}" style="background: rgba(245,158,11,0.2); border: 1px solid rgba(245,158,11,0.4); border-radius: 4px; color: #fbbf24; font-size: 10px; font-weight: 700; padding: 2px 8px; cursor: pointer;">
                  Open Console 🖥️
                </button>
                <button class="btn-join-separate" data-id="${e.id}" data-name="${r(e.name)}" data-mode="gui" style="background: rgba(245,158,11,0.2); border: 1px solid rgba(245,158,11,0.4); border-radius: 4px; color: #fbbf24; font-size: 10px; font-weight: 700; padding: 2px 6px; cursor: pointer;" title="${p(`vm.open_separate`,`Open in Separate Window`)}">
                  ↗
                </button>
              </div>
            </div>
          `:e.ip_address?`
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; padding: 4px 8px; background: rgba(14,165,233,0.1); border: 1px solid rgba(14,165,233,0.25); border-radius: 4px; margin-bottom: 10px; position: relative;">
              <span style="color: #38bdf8; font-family: monospace; display: flex; align-items: center; gap: 5px;">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                ${r(e.ip_address)}
              </span>
              <div style="display: flex; align-items: center; gap: 4px;">
                <button class="btn-copy-ip" data-ip="${r(e.ip_address)}" style="background: none; border: none; cursor: pointer; color: var(--muted); padding: 2px 4px; display: flex; align-items: center;" title="Copy IP">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                </button>
              </div>

              <!-- Quick Connect Popover -->
              <div id="vm-join-popover-${e.id}" class="vm-join-popover" style="display: none;">
                <div style="font-size: 10px; font-weight: 800; color: var(--muted); padding-bottom: 4px; border-bottom: 1px solid rgba(255,255,255,0.06); margin-bottom: 4px;">CONNECT TO ${r(e.name).toUpperCase()}</div>
                <div class="join-popover-item btn-join-gui" data-id="${e.id}" data-name="${r(e.name)}">
                  <span>🖥️ ${p(`vm.open_gui`,`Open KVM GUI Desktop (Display :0)`)}</span>
                  <span style="font-size: 9px; color: #38bdf8;">noVNC</span>
                </div>
                <div class="join-popover-item btn-join-separate" data-id="${e.id}" data-name="${r(e.name)}" data-mode="gui">
                  <span>↗ ${p(`vm.open_separate`,`Open in Separate Window`)}</span>
                  <span style="font-size: 9px; color: #38bdf8;">Pop Out</span>
                </div>
                <div class="join-popover-item btn-join-console" data-id="${e.id}" data-name="${r(e.name)}">
                  <span>📟 ${p(`vm.open_serial`,`Open Serial Terminal (TTY)`)}</span>
                  <span style="font-size: 9px; color: #34d399;">TTY / CLI</span>
                </div>
                <div class="join-popover-item btn-join-web" data-ip="${r(e.ip_address)}">
                  <span>🌐 ${p(`vm.open_web`,`Open Web UI (HTTP)`)}</span>
                  <span style="font-size: 9px; color: #a78bfa;">http://${r(e.ip_address)}</span>
                </div>
                <div class="join-popover-item btn-join-vnc" data-id="${e.id}">
                  <span>🔗 ${p(`vm.native_vnc`,`Native VNC Client (vnc://)`)}</span>
                  <span style="font-size: 9px; color: #f59e0b;">Port ${s}</span>
                </div>
                <div class="join-popover-item btn-join-rdp" data-ip="${r(e.ip_address)}">
                  <span>🪟 ${p(`vm.rdp`,`Remote Desktop (RDP)`)}</span>
                  <span style="font-size: 9px; color: #38bdf8;">${r(e.ip_address)}:3389</span>
                </div>
                <div class="join-popover-item btn-join-ssh" data-ip="${r(e.ip_address)}">
                  <span>💻 ${p(`vm.copy_ssh`,`Copy SSH Command`)}</span>
                  <span style="font-size: 9px; font-family: monospace; color: #38bdf8;">${r(d)}</span>
                </div>
                <div class="join-popover-item btn-join-ip" data-ip="${r(e.ip_address)}">
                  <span>📋 ${p(`vm.copy_ip`,`Copy IP Address`)}</span>
                  <span style="font-size: 9px; font-family: monospace; color: #38bdf8;">${r(e.ip_address)}</span>
                </div>
                <div class="join-popover-item btn-join-details" data-id="${e.id}" style="border-top: 1px solid rgba(255,255,255,0.08); margin-top: 2px; color: #38bdf8;">
                  <span>⚡ Multi-Protocol Drawer...</span>
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                </div>
              </div>
            </div>
          `:i?`
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; padding: 6px 10px; background: rgba(14,165,233,0.08); border: 1px solid rgba(14,165,233,0.2); border-radius: 4px; margin-bottom: 10px;">
              <span style="color: #38bdf8; display: flex; align-items: center; gap: 6px;">
                <span>🖥️</span>
                <span>Console Display Active</span>
              </span>
              <div style="display: flex; gap: 4px;">
                <button class="btn-join-gui" data-id="${e.id}" data-name="${r(e.name)}" style="background: rgba(14,165,233,0.2); border: 1px solid rgba(14,165,233,0.4); border-radius: 4px; color: #38bdf8; font-size: 10px; font-weight: 700; padding: 2px 8px; cursor: pointer;">
                  Open Console 🖥️
                </button>
                <button class="btn-join-separate" data-id="${e.id}" data-name="${r(e.name)}" data-mode="gui" style="background: rgba(14,165,233,0.2); border: 1px solid rgba(14,165,233,0.4); border-radius: 4px; color: #38bdf8; font-size: 10px; font-weight: 700; padding: 2px 6px; cursor: pointer;" title="${p(`vm.open_separate`,`Open in Separate Window`)}">
                  ↗
                </button>
              </div>
            </div>
          `:``}
        </div>

        <div class="vm-card-actions" style="display: flex; gap: 6px; margin-top: 10px; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 10px; flex-wrap: wrap;">
          ${!i&&!a?`
            <button class="btn-vm-action btn-vm-start" data-id="${e.id}" data-act="start" style="flex: 1;" title="${p(`vm.start`,`Start`)}">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              <span>${p(`vm.start`,`Start`)}</span>
            </button>
            <button class="btn-vm-action btn-vm-edit" data-id="${e.id}" title="Edit VM Configuration">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
              <span>Edit</span>
            </button>
            <button class="btn-vm-action btn-vm-snapshots" data-id="${e.id}" title="${p(`vm.snapshots`,`Snapshots & Rollback`)}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
              <span>${p(`vm.snapshots_short`,`Snapshots`)}</span>
            </button>
            <button class="btn-vm-action btn-vm-delete" data-id="${e.id}" data-name="${r(e.name)}" title="${p(`vm.delete`,`Delete`)}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
              <span>${p(`vm.delete`,`Delete`)}</span>
            </button>
          `:``}
          ${i?`
            <button class="btn-vm-action btn-vm-pause" data-id="${e.id}" data-act="pause" style="flex: 1;" title="${p(`vm.pause`,`Pause`)}">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
              <span>${p(`vm.pause`,`Pause`)}</span>
            </button>
            <button class="btn-vm-action btn-vm-restart" data-id="${e.id}" data-act="restart" style="flex: 1;" title="Restart VM">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
              <span>Restart</span>
            </button>
            <button class="btn-vm-action btn-vm-acpi" data-id="${e.id}" data-act="stop" style="flex: 1;" title="ACPI Shutdown (Graceful Power Off)">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg>
              <span>Shutdown</span>
            </button>
            <button class="btn-vm-action btn-vm-stop btn-vm-force-off" data-id="${e.id}" data-act="force_off" style="flex: 1;" title="Force Stop (Hard Power Cut)">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>
              <span>Force Stop</span>
            </button>
            <button class="btn-vm-gui" data-id="${e.id}" title="${p(`vm.gui`,`KVM GUI`)}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
              <span>${p(`vm.gui`,`KVM GUI`)}</span>
            </button>
            <button class="btn-vm-console" data-id="${e.id}" title="${p(`vm.console`,`Console`)}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
              <span>${p(`vm.console`,`Console`)}</span>
            </button>
            <button class="btn-vm-action btn-vm-edit" data-id="${e.id}" title="Edit VM Configuration">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
              <span>Edit</span>
            </button>
            <button class="btn-vm-action btn-vm-snapshots" data-id="${e.id}" title="${p(`vm.snapshots`,`Snapshots & Rollback`)}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
              <span>${p(`vm.snapshots_short`,`Snapshots`)}</span>
            </button>
          `:``}
          ${a?`
            <button class="btn-vm-action btn-vm-resume" data-id="${e.id}" data-act="resume" style="flex: 1;" title="${p(`vm.resume`,`Resume`)}">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              <span>${p(`vm.resume`,`Resume`)}</span>
            </button>
            <button class="btn-vm-action btn-vm-acpi" data-id="${e.id}" data-act="stop" style="flex: 1;" title="ACPI Shutdown">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg>
              <span>Shutdown</span>
            </button>
            <button class="btn-vm-action btn-vm-stop btn-vm-force-off" data-id="${e.id}" data-act="force_off" style="flex: 1;" title="Force Stop">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>
              <span>Force Stop</span>
            </button>
            <button class="btn-vm-action btn-vm-edit" data-id="${e.id}" title="Edit VM Configuration">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
              <span>Edit</span>
            </button>
            <button class="btn-vm-action btn-vm-snapshots" data-id="${e.id}" title="${p(`vm.snapshots`,`Snapshots & Rollback`)}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
              <span>${p(`vm.snapshots_short`,`Snapshots`)}</span>
            </button>
          `:``}
          <button type="button" class="btn-vm-more-sheet" data-id="${e.id}" title="More Actions" style="display:none;">···</button>
        </div>
      </div>
    `}function O(e){e.querySelectorAll(`.btn-vm-more-sheet`).forEach(e=>{e.onclick=t=>{t.stopPropagation();let n=e.dataset.id,r=h.find(e=>e.id===n),a=r?r.name:`Virtual Machine`,o=(r?.state||`stopped`).toLowerCase(),s=o===`running`,c=o===`paused`,l=e.closest(`.vm-card`),u=[];s?u.push({icon:`🖥️`,label:p(`vm.gui`,`KVM GUI`),onClick:()=>ae(n,a,`gui`)},{icon:`⌨️`,label:p(`vm.console`,`Console (Serial TTY)`),onClick:()=>ae(n,a,`cli`)},{icon:`📸`,label:p(`vm.snapshots`,`Snapshots & Rollback`),onClick:()=>de(n)},{icon:`⏸️`,label:p(`vm.pause`,`Pause VM`),onClick:()=>l?.querySelector(`.btn-vm-pause`)?.click()},{icon:`🔄`,label:`Restart VM`,onClick:()=>l?.querySelector(`.btn-vm-restart`)?.click()},{icon:`⏻`,label:`ACPI Shutdown`,onClick:()=>l?.querySelector(`.btn-vm-acpi`)?.click()},{icon:`⏹️`,label:`Force Stop (Hard Power Cut)`,destructive:!0,onClick:()=>l?.querySelector(`.btn-vm-force-off`)?.click()},{icon:`✏️`,label:`Edit VM Configuration`,onClick:()=>A(n)}):c?u.push({icon:`▶️`,label:p(`vm.resume`,`Resume VM`),onClick:()=>l?.querySelector(`.btn-vm-resume`)?.click()},{icon:`📸`,label:p(`vm.snapshots`,`Snapshots & Rollback`),onClick:()=>de(n)},{icon:`⏻`,label:`ACPI Shutdown`,onClick:()=>l?.querySelector(`.btn-vm-acpi`)?.click()},{icon:`⏹️`,label:`Force Stop (Hard Power Cut)`,destructive:!0,onClick:()=>l?.querySelector(`.btn-vm-force-off`)?.click()},{icon:`✏️`,label:`Edit VM Configuration`,onClick:()=>A(n)}):u.push({icon:`▶️`,label:`Start VM`,onClick:()=>l?.querySelector(`.btn-vm-start`)?.click()},{icon:`📸`,label:p(`vm.snapshots`,`Snapshots & Rollback`),onClick:()=>de(n)},{icon:`✏️`,label:`Edit VM Configuration`,onClick:()=>A(n)},{icon:`🗑️`,label:p(`vm.delete`,`Delete VM`),destructive:!0,onClick:()=>l?.querySelector(`.btn-vm-delete`)?.click()}),i({title:a,subtitle:`${o.toUpperCase()} • ${r?.vcpus||2} vCPU • ${r?.memory_mb||2048} MB`,items:u})}}),e.querySelectorAll(`.btn-vm-action`).forEach(e=>{e.onclick=async()=>{let n=e.dataset.id,r=e.dataset.act,i=h.find(e=>e.id===n),a=i?i.name:`Virtual Machine`;try{await t.post(`/api/vms/${n}/action`,{action:r}),c(`VM action '${r}' completed`,`success`),b()}catch(e){let t=e.detail||e.message||`Unknown hypervisor error`;r===`start`||r===`restart`?k(a,t,n):c(`Action failed: ${t}`,`error`)}}}),e.querySelectorAll(`.btn-vm-edit`).forEach(e=>{e.onclick=t=>{t.stopPropagation();let n=e.dataset.id;A(n)}}),e.querySelectorAll(`.btn-vm-snapshots`).forEach(e=>{e.onclick=t=>{t.stopPropagation();let n=e.dataset.id;de(n)}}),e.querySelectorAll(`.btn-copy-vnc`).forEach(e=>{e.onclick=async t=>{t.stopPropagation();let n=e.dataset.uri;await P(n)?c(`Copied VNC URI '${n}'`,`info`):c(`Failed to copy VNC URI`,`error`)}}),e.querySelectorAll(`.btn-copy-ssh-cmd`).forEach(e=>{e.onclick=async t=>{t.stopPropagation();let n=e.dataset.cmd;await P(n)?c(`Copied '${n}' to clipboard`,`info`):c(`Failed to copy SSH command`,`error`)}}),e.querySelectorAll(`.btn-vm-delete`).forEach(e=>{e.onclick=()=>{let n=e.dataset.id,r=e.dataset.name;l(p(`vm.delete`,`Delete`),`${p(`vm.delete_confirm`,`Are you sure you want to delete virtual machine`)} '${r}'?`,async()=>{try{await t.delete(`/api/vms/${n}`),c(`VM '${r}' deleted`,`success`),b()}catch(e){c(`Delete failed: ${e.message}`,`error`)}})}}),e.querySelectorAll(`.btn-copy-ip`).forEach(e=>{e.onclick=async t=>{t.stopPropagation();let n=e.dataset.ip;await P(n)?c(`Copied ${n} to clipboard`,`info`):c(`Failed to copy ${n}`,`error`)}}),e.querySelectorAll(`.btn-vm-join-toggle`).forEach(e=>{e.onclick=t=>{t.stopPropagation();let n=e.dataset.id,r=document.getElementById(`vm-join-popover-${n}`);if(r){let e=r.style.display===`none`;document.querySelectorAll(`.vm-join-popover`).forEach(e=>e.style.display=`none`),r.style.display=e?`flex`:`none`}}}),e.querySelectorAll(`.btn-join-ssh`).forEach(e=>{e.onclick=async t=>{t.stopPropagation();let n=`ssh root@${e.dataset.ip}`;await P(n)&&c(`Copied '${n}' to clipboard`,`info`),document.querySelectorAll(`.vm-join-popover`).forEach(e=>e.style.display=`none`)}}),e.querySelectorAll(`.btn-join-ip`).forEach(e=>{e.onclick=async t=>{t.stopPropagation();let n=e.dataset.ip;await P(n)&&c(`Copied ${n} to clipboard`,`info`),document.querySelectorAll(`.vm-join-popover`).forEach(e=>e.style.display=`none`)}}),e.querySelectorAll(`.btn-join-separate`).forEach(e=>{e.onclick=t=>{t.stopPropagation();let n=e.dataset.id,r=h.find(e=>e.id===n),i=r?r.name:e.dataset.name||`Virtual Machine`,a=e.dataset.mode||`gui`;document.querySelectorAll(`.vm-join-popover`).forEach(e=>e.style.display=`none`),oe(n,i,a)}}),e.querySelectorAll(`.btn-vm-gui, .btn-join-gui`).forEach(e=>{e.onclick=t=>{t.stopPropagation();let n=e.dataset.id,r=h.find(e=>e.id===n),i=r?r.name:e.dataset.name||`Virtual Machine`;document.querySelectorAll(`.vm-join-popover`).forEach(e=>e.style.display=`none`),ae(n,i,`gui`)}}),e.querySelectorAll(`.btn-join-console, .btn-vm-console`).forEach(e=>{e.onclick=t=>{t.stopPropagation();let n=e.dataset.id,r=h.find(e=>e.id===n),i=r?r.name:e.dataset.name||`Virtual Machine`;document.querySelectorAll(`.vm-join-popover`).forEach(e=>e.style.display=`none`),ae(n,i,`cli`)}}),e.querySelectorAll(`.btn-join-web`).forEach(e=>{e.onclick=t=>{t.stopPropagation();let n=e.dataset.ip;n&&window.open(`http://${n}`,`_blank`),document.querySelectorAll(`.vm-join-popover`).forEach(e=>e.style.display=`none`)}}),e.querySelectorAll(`.btn-join-vnc`).forEach(e=>{e.onclick=async t=>{t.stopPropagation();let n=e.dataset.id,r=5900+(parseInt(n,10)||1)%10,i=`vnc://${window.location.hostname||`127.0.0.1`}:${r}`;await P(i)&&c(`Copied VNC URI '${i}' for native client`,`info`),document.querySelectorAll(`.vm-join-popover`).forEach(e=>e.style.display=`none`)}}),e.querySelectorAll(`.btn-join-rdp`).forEach(e=>{e.onclick=async t=>{t.stopPropagation();let n=`${e.dataset.ip}:3389`;await P(n)&&c(`Copied RDP Address '${n}'`,`info`),document.querySelectorAll(`.vm-join-popover`).forEach(e=>e.style.display=`none`)}}),e.querySelectorAll(`.btn-join-details`).forEach(e=>{e.onclick=t=>{t.stopPropagation();let n=e.dataset.id;document.querySelectorAll(`.vm-join-popover`).forEach(e=>e.style.display=`none`),j(n)}}),window._vmJoinDismissRegistered||(window._vmJoinDismissRegistered=!0,document.addEventListener(`click`,()=>{document.querySelectorAll(`.vm-join-popover`).forEach(e=>e.style.display=`none`)}))}function k(e,t,n=null){let i=document.getElementById(`modal-qemu-error`);i?i.className=`smart-modal-backdrop`:(i=document.createElement(`div`),i.id=`modal-qemu-error`,i.className=`smart-modal-backdrop`,document.body.appendChild(i)),i.innerHTML=`
    <div class="smart-modal-window vm-modal-window" style="max-width: 520px; width: 92%;">
      <div class="smart-modal-header" style="background: rgba(239, 68, 68, 0.15); border-bottom: 1px solid rgba(239, 68, 68, 0.3);">
        <div class="smart-modal-title" style="color: #f87171; display: flex; align-items: center; gap: 8px;">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          <span>QEMU Hypervisor Launch Failure</span>
        </div>
        <button id="qemu-error-close" class="modal-close-btn" style="background: none; border: none; color: var(--muted); cursor: pointer; font-size: 16px;">✕</button>
      </div>
      <div class="smart-modal-body" style="padding: 16px 20px; display: flex; flex-direction: column; gap: 14px;">
        <div style="font-size: 13px; color: #fff;">
          Failed to start virtual machine <strong>${r(e)}</strong>. The hypervisor process encountered a critical error:
        </div>
        <div class="qemu-error-box" style="background: rgba(0,0,0,0.5); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 6px; padding: 12px; font-family: monospace; font-size: 11px; color: #fca5a5; line-height: 1.5; white-space: pre-wrap; word-break: break-all; max-height: 160px; overflow-y: auto;">${r(t||`Process exited prematurely with non-zero exit code.`)}</div>
        <div style="font-size: 11px; color: var(--muted); line-height: 1.4;">
          <strong>Recommended Troubleshooting:</strong>
          <ul style="margin: 6px 0 0 16px; padding: 0;">
            <li>Verify KVM kernel acceleration module (<code>/dev/kvm</code>) is accessible.</li>
            <li>Ensure the boot ISO and virtual disk paths exist and are not locked.</li>
            <li>Confirm host server has adequate free RAM headroom.</li>
          </ul>
        </div>
      </div>
      <div class="smart-modal-footer" style="padding: 12px 20px; display: flex; justify-content: flex-end; gap: 10px; border-top: 1px solid rgba(255,255,255,0.08);">
        <button id="btn-qemu-error-diag" class="btn-console-act" style="background: rgba(14, 165, 233, 0.2); border-color: #38bdf8; color: #38bdf8;">
          🛠️ Run KVM Diagnostics
        </button>
        ${n?`
          <button id="btn-qemu-error-edit" class="btn-console-act" style="background: rgba(255,255,255,0.08); border-color: rgba(255,255,255,0.2); color: #fff;">
            ⚙️ Edit VM Settings
          </button>
        `:``}
        <button id="btn-qemu-error-dismiss" class="btn-console-act" style="background: rgba(255,255,255,0.05); color: #cbd5e1;">
          Dismiss
        </button>
      </div>
    </div>
  `,i.classList.add(`open`),i.style.display=`flex`;let a=i.querySelector(`#qemu-error-close`),o=i.querySelector(`#btn-qemu-error-dismiss`),s=i.querySelector(`#btn-qemu-error-diag`),c=i.querySelector(`#btn-qemu-error-edit`),l=()=>{i.classList.remove(`open`),i.style.display=`none`};a&&(a.onclick=l),o&&(o.onclick=l),i.onclick=e=>{e.target===i&&l()},s&&(s.onclick=()=>{l(),M()}),c&&n&&(c.onclick=()=>{l(),A(n)})}function A(e,n=null){let i=document.getElementById(`modal-vm-edit`);i?i.className=`smart-modal-backdrop`:(i=document.createElement(`div`),i.id=`modal-vm-edit`,i.className=`smart-modal-backdrop`,document.body.appendChild(i));let a=n||h.find(t=>t.id===e),o=n=>{let a=n.state===`running`,o=g?.memory_budget||{total_host_ram_gb:32,safe_max_vm_ram_gb:28.8,safe_slider_max_gb:28,safe_headroom_gb:20.8,override_max_ram_gb:31},s=g?.cpu_capacity?.host_threads||8,l=n.boot_order||(n.iso_path?`iso`:`disk`),f=n.firmware||`seabios`,m=n.video_adapter||n.display_adapter||`virtio-gpu`,h=Array.isArray(n.usb_passthrough)?n.usb_passthrough.map(e=>({...e})):[],v=Array.isArray(n.pci_passthrough)?n.pci_passthrough.map(e=>({...e})):[];i.innerHTML=`
      <div class="smart-modal-window vm-modal-window" style="max-width: 580px; width: 92%; max-height: 88vh; display: flex; flex-direction: column; overflow: hidden;">
        <div class="smart-modal-header" style="cursor: move; user-select: none; display: flex; justify-content: space-between; align-items: center;">
          <div class="smart-modal-title" style="display: flex; align-items: center; gap: 8px;">
            <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
            <span>Edit VM Configuration: ${r(n.name)}</span>
          </div>
          <div class="os-window-controls" style="display: flex; gap: 6px; align-items: center;">
            <button class="win-btn min-btn" id="vm-edit-modal-min" title="Minimize" aria-label="Minimize"></button>
            <button class="win-btn max-btn" id="vm-edit-modal-max" title="Maximize" aria-label="Maximize"></button>
            <button class="win-btn close-btn" id="vm-edit-modal-close" title="Close" aria-label="Close"></button>
          </div>
        </div>

      <div class="smart-modal-body" style="flex: 1; overflow-y: auto; overflow-x: hidden; display: flex; flex-direction: column; gap: 14px; padding: 18px 22px;">
        ${a?`
          <div style="background: rgba(14,165,233,0.12); border: 1px solid rgba(14,165,233,0.3); border-radius: 6px; padding: 10px 14px; font-size: 11px; color: #38bdf8; display: flex; align-items: center; gap: 8px;">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
            <span>This VM is currently <strong>running</strong>. Hardware changes (vCPUs, RAM, boot order) will take full effect on next VM restart.</span>
          </div>
        `:``}

        <!-- General Info -->
        <div>
          <label style="display: block; font-size: 11px; font-weight: 700; color: var(--muted); margin-bottom: 6px;">VM Name *</label>
          <input type="text" id="vm-edit-name" value="${r(n.name||``)}" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.12); color: #fff; font-size: 12px; box-sizing: border-box;" />
        </div>

        <div>
          <label style="display: block; font-size: 11px; font-weight: 700; color: var(--muted); margin-bottom: 6px;">Description</label>
          <input type="text" id="vm-edit-desc" value="${r(n.description||``)}" placeholder="Appliance description" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.12); color: #fff; font-size: 12px; box-sizing: border-box;" />
        </div>

        <!-- Snapshots Quick Launcher -->
        <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 12px 14px;">
          <div>
            <div style="font-size: 12px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 6px;">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--accent, #38bdf8);"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
              <span>Snapshots & Rollback Checkpoints</span>
            </div>
            <div style="font-size: 11px; color: var(--muted); margin-top: 2px;">Create point-in-time state backups or revert to previous checkpoints.</div>
          </div>
          <button type="button" id="vm-edit-open-snapshots" class="btn-vm-action btn-vm-snapshots" style="padding: 5px 12px; font-size: 11px; font-weight: 700; cursor: pointer; display: inline-flex; align-items: center; gap: 6px;">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
            <span>${p(`vm.manage_snapshots`,`Manage Snapshots`)}</span>
          </button>
        </div>

        <!-- RAM Allocation & Dynamic Headroom -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 12px; font-weight: 700; color: #fff;">RAM Allocation (Dynamic Headroom)</span>
            <span id="vm-edit-ram-display" style="font-size: 12px; font-weight: 700; color: #38bdf8;">${n.ram_gb||4} GB</span>
          </div>
          <input type="range" id="vm-edit-ram-slider" min="0.5" max="${Math.max(o.safe_slider_max_gb,n.ram_gb||4)}" step="0.5" value="${n.ram_gb||4}" style="width: 100%; accent-color: var(--accent-cyan, #0ea5e9); cursor: pointer;" />
          <div style="display: flex; justify-content: space-between; font-size: 10px; color: var(--muted); margin-top: 4px;">
            <span>Min: 0.5 GB</span>
            <span id="vm-edit-slider-max-label">Safe Max: ${o.safe_slider_max_gb} GB</span>
          </div>
          <div style="margin-top: 10px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.05); display: flex; justify-content: space-between; align-items: center;">
            <label style="font-size: 11px; color: var(--muted); cursor: pointer; display: flex; align-items: center; gap: 6px;">
              <input type="checkbox" id="vm-edit-override-toggle" ${n.override_active?`checked`:``} style="accent-color: #f59e0b;" />
              <span>Advanced Override (Bypass Headroom)</span>
            </label>
            <span id="vm-edit-override-pill" style="display: ${n.override_active?`inline-block`:`none`}; font-size: 9px; padding: 2px 6px; border-radius: 4px; background: rgba(245,158,11,0.2); color: #fbbf24; border: 1px solid rgba(245,158,11,0.4);">
              ⚡ Host reserve bypassed
            </span>
          </div>
        </div>

        <!-- vCPUs Slider -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 12px; font-weight: 700; color: #fff;">vCPU Cores</span>
            <span id="vm-edit-vcpu-display" style="font-size: 12px; font-weight: 700; color: #fff;">${n.vcpus||2} vCPUs</span>
          </div>
          <input type="range" id="vm-edit-vcpu-slider" min="1" max="${Math.max(s,n.vcpus||2)}" step="1" value="${n.vcpus||2}" style="width: 100%; accent-color: var(--accent-cyan, #0ea5e9); cursor: pointer;" />
          <div style="display: flex; justify-content: space-between; font-size: 10px; color: var(--muted); margin-top: 4px;">
            <span>1 vCPU</span>
            <span>Physical Limit: ${s} Threads</span>
          </div>
          <div id="vm-edit-overcommit-warning" style="display: ${(n.vcpus||2)>s?`block`:`none`}; margin-top: 8px; font-size: 10px; padding: 6px 10px; border-radius: 4px; background: rgba(245,158,11,0.15); color: #fbbf24; border: 1px solid rgba(245,158,11,0.3);">
            ⚠️ Soft warning: Exceeds physical host threads.
          </div>
        </div>

        <!-- ISO Attach / Detach & Boot Order -->
        <div style="display: flex; flex-direction: column; gap: 10px; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <label style="font-size: 11px; font-weight: 700; color: var(--muted);">Attached ISO Image (CD-ROM)</label>
              ${n.iso_path?`<span style="font-size: 10px; color: #fbbf24;">💿 Currently Attached</span>`:``}
            </div>
            <select id="vm-edit-iso" class="tz-select" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: #1e293b; border: 1px solid rgba(255,255,255,0.12); color: #fff; font-size: 12px; box-sizing: border-box;">
              <option value="">None (Detach ISO / Empty Tray)</option>
              ${_.map(e=>`<option value="${r(e.path)}" ${e.path===n.iso_path?`selected`:``}>${r(e.name)} (${e.size_formatted})</option>`).join(``)}
            </select>
          </div>

          <div>
            <label style="display: block; font-size: 11px; font-weight: 700; color: var(--muted); margin-bottom: 6px;">Boot Priority Order</label>
            <div class="vm-boot-order-group">
              <label class="boot-order-label">
                <input type="radio" name="vm-edit-boot-order" value="iso" ${l===`iso`?`checked`:``} />
                <span>💿 Boot from ISO first</span>
              </label>
              <label class="boot-order-label">
                <input type="radio" name="vm-edit-boot-order" value="disk" ${l===`disk`?`checked`:``} />
                <span>💽 Boot from Disk</span>
              </label>
            </div>
          </div>
        </div>

        <!-- Firmware & Boot Architecture -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="margin-bottom: 8px;">
            <div style="font-size: 12px; font-weight: 700; color: #fff;" data-i18n="vm.firmware_title">${p(`vm.firmware_title`,`Firmware & Boot Architecture`)}</div>
            <div style="font-size: 10px; color: var(--muted);" data-i18n="vm.firmware_desc">${p(`vm.firmware_desc`,`Select hypervisor firmware initialization and virtual hardware security.`)}</div>
          </div>
          <div class="vm-firmware-group">
            <label class="firmware-label">
              <div style="display: flex; align-items: center; gap: 6px; font-weight: 700;">
                <input type="radio" name="vm-edit-firmware" value="seabios" ${f===`seabios`?`checked`:``} />
                <span data-i18n="vm.firmware_seabios">${p(`vm.firmware_seabios`,`SeaBIOS (Legacy BIOS)`)}</span>
              </div>
              <div class="firmware-label-sub">MBR partitions, older Linux & Windows 7/10</div>
            </label>
            <label class="firmware-label">
              <div style="display: flex; align-items: center; gap: 6px; font-weight: 700;">
                <input type="radio" name="vm-edit-firmware" value="uefi" ${f===`uefi`?`checked`:``} />
                <span data-i18n="vm.firmware_uefi">${p(`vm.firmware_uefi`,`OVMF / UEFI (Modern / Win 11)`)}</span>
              </div>
              <div class="firmware-label-sub">Pure 64-bit UEFI, NVRAM persistence, Secure Boot</div>
            </label>
          </div>

          <!-- Virtual TPM 2.0 Toggle -->
          <div style="margin-top: 10px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.05); display: flex; justify-content: space-between; align-items: center;">
            <label style="font-size: 11px; color: #fff; cursor: pointer; display: flex; align-items: center; gap: 6px;">
              <input type="checkbox" id="vm-edit-tpm" ${n.tpm_enabled?`checked`:``} style="accent-color: var(--accent-cyan, #0ea5e9);" />
              <span data-i18n="vm.tpm_title">${p(`vm.tpm_title`,`Enable Virtual TPM 2.0 (vTPM)`)}</span>
            </label>
            ${x()}
          </div>
        </div>

        <!-- Display & Video Adapter -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div>
              <div style="font-size: 12px; font-weight: 700; color: #fff;" data-i18n="vm.video_title">${p(`vm.video_title`,`Display & Video Adapter`)}</div>
              <div style="font-size: 10px; color: var(--muted);">Select virtual GPU hardware adapter or headless console mode</div>
            </div>
            <span style="font-size: 9px; padding: 2px 6px; border-radius: 4px; background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.3);">
              GPU Accelerated
            </span>
          </div>
          <select id="vm-edit-video-adapter" class="tz-select" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: #1e293b; border: 1px solid rgba(255,255,255,0.12); color: #fff; font-size: 12px; box-sizing: border-box;">
            <option value="virtio-gpu" ${m===`virtio-gpu`?`selected`:``}>VirtIO-GPU (Recommended / Linux 2D/3D Accel)</option>
            <option value="qxl" ${m===`qxl`?`selected`:``}>QXL (SPICE / Windows Drivers)</option>
            <option value="vga" ${m===`vga`?`selected`:``}>Standard VGA (Universal Compatibility)</option>
            <option value="none" ${m===`none`?`selected`:``}>Headless (Serial Console Only - Zero VRAM)</option>
          </select>
        </div>

        <!-- Host USB Passthrough -->
        <div class="vm-config-card" style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px; flex-shrink: 0;">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; gap: 10px;">
            <div>
              <div style="font-size: 12px; font-weight: 700; color: #fff;" data-i18n="vm.usb_title">${p(`vm.usb_title`,`Host USB Device Passthrough`)}</div>
              <div style="font-size: 10px; color: var(--muted);" data-i18n="vm.usb_desc">${p(`vm.usb_desc`,`Attach physical host USB peripherals directly into the guest VM.`)}</div>
            </div>
            <button type="button" id="btn-edit-toggle-custom-usb" class="btn-pill-toggle" data-i18n="vm.usb_custom_btn" style="padding: 4px 8px; font-size: 10px; white-space: nowrap; flex-shrink: 0; cursor: pointer;">
              ${p(`vm.usb_custom_btn`,`+ Custom VID:PID`)}
            </button>
          </div>

          <!-- Dynamic host USB selector row -->
          <div class="usb-select-row">
            <select id="vm-edit-host-usb-select" class="tz-select">
              <option value="">Scanning host USB devices...</option>
            </select>
            <button type="button" id="btn-edit-add-usb-device" class="btn-attach-usb">
              ${p(`vm.usb_add_btn`,`+ Attach Device`)}
            </button>
          </div>

          <!-- Custom USB inputs (hidden by default) -->
          <div id="vm-edit-custom-usb-wrap" class="usb-custom-row" style="display: none;">
            <input type="text" id="vm-edit-custom-vid" placeholder="VID (10c4)" maxlength="4" style="width: 74px; flex-shrink: 0; padding: 5px 8px; border-radius: 4px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
            <input type="text" id="vm-edit-custom-pid" placeholder="PID (ea60)" maxlength="4" style="width: 74px; flex-shrink: 0; padding: 5px 8px; border-radius: 4px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
            <input type="text" id="vm-edit-custom-desc" class="usb-custom-desc" placeholder="Device Label (e.g. Zigbee Dongle)" style="padding: 5px 8px; border-radius: 4px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
            <button type="button" id="btn-edit-add-custom-usb" class="btn-console-act btn-custom-add" style="padding: 4px 10px; font-size: 11px; background: rgba(16,185,129,0.2); border-color: #34d399; color: #34d399; cursor: pointer;">
              Add
            </button>
          </div>

          <!-- Attached USB devices list -->
          <div id="vm-edit-usb-list" style="display: flex; flex-direction: column; gap: 6px; margin-top: 6px;"></div>
        </div>

        <!-- Host PCI / GPU Passthrough (VFIO) -->
        <div class="vm-config-card vm-pci-card" style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px; flex-shrink: 0;">
          <div style="margin-bottom: 8px;">
            <div style="font-size: 12px; font-weight: 700; color: #fff;" data-i18n="vm.pci_title">${p(`vm.pci_title`,`PCI / GPU Passthrough (VFIO)`)}</div>
            <div style="font-size: 10px; color: var(--muted);" data-i18n="vm.pci_desc">${p(`vm.pci_desc`,`Give the VM exclusive use of a host PCI device such as a GPU. The device must be bound to the vfio-pci driver on the host.`)}</div>
          </div>
          <div id="vm-edit-pci-list" style="display: flex; flex-direction: column; gap: 4px;"></div>
        </div>

        <!-- Host Folder Passthrough (VirtIO-FS / 9p) -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div>
              <span style="font-size: 12px; font-weight: 700; color: #fff;">Host Directory Passthrough (VirtIO-FS / 9p)</span>
              <div style="font-size: 10px; color: var(--muted);">Map host folders (/mnt/user/appdata, /mnt/storage) into guest</div>
            </div>
            <button type="button" id="btn-edit-add-host-share" class="btn-pill-toggle" style="padding: 3px 8px; font-size: 10px;">
              + Add Folder
            </button>
          </div>
          <div id="vm-edit-host-shares-list" style="display: flex; flex-direction: column; gap: 6px;"></div>
        </div>

        <!-- Secondary Virtual Disks -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div>
              <span style="font-size: 12px; font-weight: 700; color: #fff;">Secondary Virtual Disks</span>
              <div style="font-size: 10px; color: var(--muted);">Attach additional block devices (data pools, databases)</div>
            </div>
            <button type="button" id="btn-edit-add-secondary-disk" class="btn-pill-toggle" style="padding: 3px 8px; font-size: 10px;">
              + Add Disk
            </button>
          </div>
          <div id="vm-edit-secondary-disks-list" style="display: flex; flex-direction: column; gap: 6px;"></div>
        </div>

        <div>
          <label style="display: flex; align-items: center; gap: 8px; font-size: 12px; color: #fff; cursor: pointer;">
            <input type="checkbox" id="vm-edit-autostart" ${n.autostart?`checked`:``} style="accent-color: var(--accent-cyan, #0ea5e9);" />
            <span>Autostart on Boot (Start with Host OS)</span>
          </label>
        </div>
      </div>

      <div class="smart-modal-footer" style="padding: 14px 22px; display: flex; justify-content: flex-end; gap: 10px; border-top: 1px solid rgba(255,255,255,0.08); background: rgba(0,0,0,0.2);">
        <button id="vm-edit-cancel" class="btn-console-act" style="background: rgba(255,255,255,0.06); color: #cbd5e1; padding: 6px 14px;">
          Cancel
        </button>
        <button id="vm-edit-submit" class="btn-console-act" style="background: #0ea5e9; color: #fff; border-color: #38bdf8; padding: 6px 18px; font-weight: 700;">
          Save Configuration
        </button>
      </div>
    </div>
  `,i.classList.remove(`window-minimized`),i.classList.add(`open`),i.style.removeProperty(`display`),i.style.display=`flex`;let y=i.querySelector(`.smart-modal-window`),S=i.querySelector(`.smart-modal-header`);y&&(y.classList.remove(`window-minimized`),y.style.removeProperty(`display`));let C=i.querySelector(`#vm-edit-modal-close`),w=i.querySelector(`#vm-edit-modal-min`),T=i.querySelector(`#vm-edit-modal-max`),E=i.querySelector(`#vm-edit-cancel`),D=i.querySelector(`#vm-edit-submit`),O=i.querySelector(`#vm-edit-ram-slider`),k=i.querySelector(`#vm-edit-ram-display`),A=i.querySelector(`#vm-edit-vcpu-slider`),j=i.querySelector(`#vm-edit-vcpu-display`),M=i.querySelector(`#vm-edit-override-toggle`),N=i.querySelector(`#vm-edit-override-pill`),P=i.querySelector(`#vm-edit-slider-max-label`),F=i.querySelector(`#vm-edit-overcommit-warning`);y&&S&&(u(y,S,`modal-vm-edit`),y.addEventListener(`pointerdown`,()=>d(y)),d(y)),window.DockManager&&typeof window.DockManager.register==`function`&&window.DockManager.register(`modal-vm-edit`,i,`#i-vm`,`Edit: ${n.name||`VM Configuration`}`);let I=null,L=()=>{i.classList.remove(`open`),i.classList.remove(`window-minimized`),i.style.display=`none`,y&&y.classList.remove(`window-minimized`),I&&=(document.removeEventListener(`keydown`,I),null),window.DockManager&&typeof window.DockManager.unregister==`function`&&window.DockManager.unregister(`modal-vm-edit`)};I=e=>{e.key===`Escape`&&i.classList.contains(`open`)&&L()},document.addEventListener(`keydown`,I),C&&(C.onclick=L),E&&(E.onclick=L);let R=i.querySelector(`#vm-edit-open-snapshots`);R&&(R.onclick=()=>{de(e,n)}),w&&(w.onclick=e=>{e.preventDefault(),e.stopPropagation(),i.classList.add(`window-minimized`),i.classList.remove(`open`),i.style.setProperty(`display`,`none`,`important`),y&&y.classList.add(`window-minimized`),window.DockManager&&typeof window.DockManager.minimize==`function`&&window.DockManager.minimize(`modal-vm-edit`)});let z=!1,B=null;T&&(T.onclick=e=>{e.preventDefault(),e.stopPropagation(),z?(y.classList.remove(`maximized`),B?(y.style.left=B.left||``,y.style.top=B.top||``,y.style.width=B.width||`92%`,y.style.height=B.height||``,y.style.maxWidth=B.maxWidth||`580px`,y.style.maxHeight=B.maxHeight||`88vh`,y.style.position=B.position||``,y.style.borderRadius=B.borderRadius||`14px`):(y.style.left=``,y.style.top=``,y.style.width=`92%`,y.style.height=``,y.style.maxWidth=`580px`,y.style.maxHeight=`88vh`,y.style.position=``,y.style.borderRadius=`14px`),T.setAttribute(`title`,`Maximize`),T.setAttribute(`aria-label`,`Maximize`),z=!1):(B={left:y.style.left,top:y.style.top,width:y.style.width,height:y.style.height,maxWidth:y.style.maxWidth,maxHeight:y.style.maxHeight,position:y.style.position,borderRadius:y.style.borderRadius},y.classList.add(`maximized`),y.style.position=`fixed`,y.style.left=`0px`,y.style.top=`36px`,y.style.width=`100vw`,y.style.height=`calc(100vh - 36px - 72px)`,y.style.maxWidth=`100vw`,y.style.maxHeight=`calc(100vh - 36px - 72px)`,y.style.borderRadius=`0px`,T.setAttribute(`title`,`Restore`),T.setAttribute(`aria-label`,`Restore`),z=!0)}),S&&(S.ondblclick=e=>{e.target.closest(`button`)||e.target.closest(`input`)||T&&T.click()}),O&&k&&(O.oninput=()=>{k.textContent=`${parseFloat(O.value).toFixed(1)} GB`}),M&&(M.onchange=()=>{M.checked?(O.max=o.override_max_ram_gb||31,P&&(P.textContent=`Override Max: ${O.max} GB`),N&&(N.style.display=`inline-block`)):(O.max=o.safe_slider_max_gb||28,parseFloat(O.value)>O.max&&(O.value=O.max,k.textContent=`${O.value} GB`),P&&(P.textContent=`Safe Max: ${O.max} GB`),N&&(N.style.display=`none`))}),A&&j&&(A.oninput=()=>{let e=parseInt(A.value,10);j.textContent=`${e} vCPUs`,F&&(F.style.display=e>s?`block`:`none`)});let V=i.querySelector(`#vm-edit-host-shares-list`),H=i.querySelector(`#btn-edit-add-host-share`),ee=(e={})=>{let t=document.createElement(`div`);t.className=`host-share-row`,t.style.cssText=`display: flex; gap: 6px; align-items: center;`,t.innerHTML=`
      <input type="text" class="share-host-path" placeholder="/mnt/user/appdata" value="${r(e.host_path||`/mnt/user/appdata`)}" style="flex: 2; padding: 6px 8px; border-radius: 4px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
      <input type="text" class="share-mount-tag" placeholder="appdata" value="${r(e.mount_tag||`appdata`)}" style="flex: 1.2; padding: 6px 8px; border-radius: 4px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
      <select class="share-driver" style="flex: 1; padding: 6px 4px; border-radius: 4px; background: #1e293b; border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;">
        <option value="virtiofs" ${e.driver===`virtiofs`?`selected`:``}>VirtIO-FS</option>
        <option value="9p" ${e.driver===`9p`?`selected`:``}>9p</option>
      </select>
      <select class="share-mode" style="width: 60px; padding: 6px 4px; border-radius: 4px; background: #1e293b; border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;">
        <option value="rw" ${e.readonly?``:`selected`}>RW</option>
        <option value="ro" ${e.readonly?`selected`:``}>RO</option>
      </select>
      <button type="button" class="btn-remove-share" style="background: none; border: none; color: #f87171; cursor: pointer; padding: 2px 6px;">✕</button>
    `,t.querySelector(`.btn-remove-share`).onclick=()=>t.remove(),V.appendChild(t)};H&&V&&(H.onclick=()=>ee(),n.host_shares&&Array.isArray(n.host_shares)&&n.host_shares.forEach(e=>ee(e)));let U=i.querySelector(`#vm-edit-secondary-disks-list`),W=i.querySelector(`#btn-edit-add-secondary-disk`),te=(e={})=>{let t=(U.children.length||0)+1,n=document.createElement(`div`);n.className=`secondary-disk-row`,n.style.cssText=`display: flex; gap: 6px; align-items: center;`,n.innerHTML=`
      <input type="text" class="disk-name" placeholder="Disk Name" value="${r(e.name||`data-disk-${t}`)}" style="flex: 2; padding: 6px 8px; border-radius: 4px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
      <input type="number" class="disk-size" min="5" max="4000" placeholder="Size (GB)" value="${e.size_gb||50}" style="width: 80px; padding: 6px 8px; border-radius: 4px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
      <select class="disk-bus" style="width: 80px; padding: 6px 4px; border-radius: 4px; background: #1e293b; border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;">
        <option value="virtio" ${e.bus===`virtio`?`selected`:``}>virtio</option>
        <option value="sata" ${e.bus===`sata`?`selected`:``}>sata</option>
        <option value="nvme" ${e.bus===`nvme`?`selected`:``}>nvme</option>
      </select>
      <button type="button" class="btn-remove-disk" style="background: none; border: none; color: #f87171; cursor: pointer; padding: 2px 6px;">✕</button>
    `,n.querySelector(`.btn-remove-disk`).onclick=()=>n.remove(),U.appendChild(n)};W&&U&&(W.onclick=()=>te(),n.secondary_disks&&Array.isArray(n.secondary_disks)&&n.secondary_disks.forEach(e=>te(e)));let G=i.querySelector(`#vm-edit-pci-list`),ne={"0300":`GPU`,"0302":`GPU`,"0380":`GPU`,"0403":`Audio`,"0200":`Network`,"0280":`Wi-Fi`,"0108":`NVMe`,"0106":`SATA`,"0104":`RAID`,"0c03":`USB`},K=new Set([`0600`,`0601`,`0604`]),q=(e,t=!1)=>`<div class="vm-pci-note${t?` warn`:``}" style="font-size: 10px; padding: 6px 10px; border-radius: 4px; background: ${t?`rgba(245,158,11,0.12)`:`rgba(0,0,0,0.2)`}; color: ${t?`#fbbf24`:`var(--muted)`};">${r(e)}</div>`;G&&(G.innerHTML=q(p(`vm.pci_scanning`,`Scanning host PCI devices...`)),t.get(`/api/vms/iommu-groups`).then(e=>{if(!G)return;if(!e||!e.iommu_enabled){G.innerHTML=q(p(`vm.pci_no_iommu`,`IOMMU is not enabled on this host, so PCI passthrough is unavailable.`),!0);return}let t=new Set(v.map(e=>e.slot)),n=[];e.vfio_available===!1&&n.push(q(p(`vm.pci_vfio_missing`,`/dev/vfio is not available; pass it to the container to use PCI passthrough.`),!0));for(let i of e.groups||[]){let e=(i.devices||[]).filter(e=>!K.has(String(e.class_code||``).slice(0,4)));if(e.length!==0){e.length>1&&n.push(`<div class="vm-pci-group-note" style="font-size: 9px; color: var(--muted); margin-top: 4px;">${r(p(`vm.pci_group_note`,`IOMMU group {group}: pass all of its devices together`,{group:i.group_id}))}</div>`);for(let i of e){let e=String(i.slot||``).replace(/^0000:/,``).toLowerCase(),a=ne[String(i.class_code||``).slice(0,4)]||`PCI`,o=!!i.vfio_ready,s=t.has(e),c=o?`vfio-pci`:p(`vm.pci_needs_vfio`,`On {driver}; bind to vfio-pci first`,{driver:i.driver||p(`vm.pci_no_driver`,`no driver`)});n.push(`
          <label class="vm-pci-row${o?``:` disabled`}" style="display: flex; align-items: center; gap: 8px; font-size: 11px; padding: 4px 8px; border-radius: 4px; background: rgba(0,0,0,0.2); cursor: ${o||s?`pointer`:`not-allowed`}; opacity: ${o||s?`1`:`0.6`};">
            <input type="checkbox" class="vm-pci-check" data-slot="${r(e)}" data-name="${r(`${a} ${i.name||``}`.trim())}" ${s?`checked`:``} ${o||s?``:`disabled`} />
            <span style="font-weight: 700; color: #fff; min-width: 54px;">${r(a)}</span>
            <span style="font-family: monospace; color: #38bdf8;">${r(e)}</span>
            <span style="color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1;">${r(i.name||``)}</span>
            <span class="vm-pci-driver" style="font-size: 9px; color: ${o?`#34d399`:`#fbbf24`}; white-space: nowrap;">${r(c)}</span>
          </label>
        `)}}}n.length===0&&n.push(q(p(`vm.pci_none`,`No passthrough-capable PCI devices found.`))),G.innerHTML=n.join(``),G.querySelectorAll(`.vm-pci-check`).forEach(e=>{e.onchange=()=>{let t=e.dataset.slot;v=v.filter(e=>e.slot!==t),e.checked&&v.push({slot:t,name:e.dataset.name||``})}})}).catch(()=>{G.innerHTML=q(p(`vm.pci_scan_failed`,`Failed to scan host PCI devices.`),!0)}));let J=i.querySelector(`#vm-edit-usb-list`),Y=i.querySelector(`#vm-edit-host-usb-select`),re=i.querySelector(`#btn-edit-add-usb-device`),X=i.querySelector(`#btn-edit-toggle-custom-usb`),Z=i.querySelector(`#vm-edit-custom-usb-wrap`),Q=i.querySelector(`#btn-edit-add-custom-usb`),$=()=>{if(J){if(J.innerHTML=``,h.length===0){J.innerHTML=`
        <div style="font-size: 10px; color: var(--muted); padding: 8px 10px; text-align: center; background: rgba(0,0,0,0.2); border-radius: 4px;" data-i18n="vm.usb_no_devices">
          ${p(`vm.usb_no_devices`,`No host USB devices attached to this VM.`)}
        </div>
      `;return}h.forEach((e,t)=>{let n=document.createElement(`div`);n.className=`usb-device-card`,n.innerHTML=`
        <div style="display: flex; align-items: center; gap: 8px; overflow: hidden;">
          <span style="font-size: 14px;">🔌</span>
          <div style="min-width: 0;">
            <div style="font-size: 11px; font-weight: 700; color: #fff; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">
              ${r(e.description||e.product||`USB Device`)}
            </div>
            <div style="font-size: 9px; color: var(--muted);">
              ${r(e.manufacturer||`Generic`)} ${e.bus?`· Bus ${e.bus} Dev ${e.dev}`:``}
            </div>
          </div>
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
          <span class="usb-vidpid-badge">${r(e.vendor_id)}:${r(e.product_id)}</span>
          <button type="button" class="btn-remove-usb" data-idx="${t}" style="background: none; border: none; color: #f87171; cursor: pointer; padding: 2px 6px; font-size: 12px;" title="Remove device">✕</button>
        </div>
      `,n.querySelector(`.btn-remove-usb`).onclick=()=>{h.splice(t,1),$()},J.appendChild(n)})}};$(),t.get(`/api/vms/usb-devices`).then(e=>{Y&&(Y.innerHTML=`<option value="">-- Select connected host USB device --</option>`,Array.isArray(e)&&e.length>0?e.forEach(e=>{let t=document.createElement(`option`);t.value=JSON.stringify({vendor_id:e.vendor_id,product_id:e.product_id,description:e.description||e.product,manufacturer:e.manufacturer,bus:e.bus,dev:e.dev});let n=e.is_root_hub?` [Root Hub]`:``;t.textContent=`[${e.vendor_id}:${e.product_id}] ${e.description||e.product}${n}`,Y.appendChild(t)}):Y.innerHTML=`<option value="">No USB devices detected on host</option>`)}).catch(()=>{Y&&(Y.innerHTML=`<option value="">Failed to scan USB devices</option>`)}),re&&Y&&(re.onclick=()=>{let e=Y.value;if(!e){c(`Select a host USB device to attach`,`warning`);return}try{let t=JSON.parse(e);h.some(e=>e.vendor_id===t.vendor_id&&e.product_id===t.product_id)?c(`Device is already attached to this VM`,`warning`):(h.push(t),$(),c(`Attached USB device: ${t.description||t.vendor_id}`,`info`))}catch{}}),X&&Z&&(X.onclick=e=>{e&&(e.preventDefault(),e.stopPropagation());let t=Z.style.display===`none`||typeof window<`u`&&window.getComputedStyle&&window.getComputedStyle(Z).display===`none`;if(Z.style.display=t?`flex`:`none`,X.classList.toggle(`active`,t),X.textContent=t?p(`vm.usb_custom_close_btn`,`− Custom VID:PID`):p(`vm.usb_custom_btn`,`+ Custom VID:PID`),t){let e=i.querySelector(`#vm-edit-custom-vid`);e&&e.focus()}}),[`#vm-edit-custom-vid`,`#vm-edit-custom-pid`,`#vm-edit-custom-desc`].forEach(e=>{let t=i.querySelector(e);t&&t.addEventListener(`keydown`,e=>{e.key===`Enter`&&(e.preventDefault(),Q?.click())})}),Q&&(Q.onclick=()=>{let e=i.querySelector(`#vm-edit-custom-vid`)?.value?.trim().toLowerCase().replace(`0x`,``),t=i.querySelector(`#vm-edit-custom-pid`)?.value?.trim().toLowerCase().replace(`0x`,``),n=i.querySelector(`#vm-edit-custom-desc`)?.value?.trim()||`USB Device (${e}:${t})`;if(!e||!t||!/^[0-9a-fA-F]{1,4}$/.test(e)||!/^[0-9a-fA-F]{1,4}$/.test(t)){c(`Please enter valid 4-character hex VID and PID (e.g. 10c4, ea60)`,`warning`);return}h.some(n=>n.vendor_id===e&&n.product_id===t)?c(`Device is already attached to this VM`,`warning`):(h.push({vendor_id:e,product_id:t,description:n,manufacturer:`Custom`}),$(),i.querySelector(`#vm-edit-custom-vid`).value=``,i.querySelector(`#vm-edit-custom-pid`).value=``,i.querySelector(`#vm-edit-custom-desc`).value=``,c(`Added custom USB device [${e}:${t}]`,`info`))}),D&&(D.onclick=async()=>{let r=i.querySelector(`#vm-edit-name`)?.value?.trim(),a=i.querySelector(`#vm-edit-desc`)?.value?.trim(),o=parseFloat(i.querySelector(`#vm-edit-ram-slider`)?.value||n.ram_gb),s=parseInt(i.querySelector(`#vm-edit-vcpu-slider`)?.value||n.vcpus,10),l=i.querySelector(`#vm-edit-iso`)?.value||null,u=i.querySelector(`input[name="vm-edit-boot-order"]:checked`)?.value||`iso`,d=i.querySelector(`input[name="vm-edit-firmware"]:checked`)?.value||n.firmware||`seabios`,f=i.querySelector(`#vm-edit-video-adapter`)?.value||n.video_adapter||`virtio-gpu`,p=!!i.querySelector(`#vm-edit-tpm`)?.checked,m=i.querySelector(`#vm-edit-autostart`)?.checked??n.autostart,g=i.querySelector(`#vm-edit-override-toggle`)?.checked??!1,_=[];i.querySelectorAll(`.host-share-row`).forEach(e=>{let t=e.querySelector(`.share-host-path`)?.value?.trim(),n=e.querySelector(`.share-mount-tag`)?.value?.trim(),r=e.querySelector(`.share-driver`)?.value||`virtiofs`,i=e.querySelector(`.share-mode`)?.value===`ro`;t&&n&&_.push({host_path:t,mount_tag:n,driver:r,readonly:i})});let y=[];if(i.querySelectorAll(`.secondary-disk-row`).forEach(e=>{let t=e.querySelector(`.disk-name`)?.value?.trim(),n=parseInt(e.querySelector(`.disk-size`)?.value,10),r=e.querySelector(`.disk-bus`)?.value||`virtio`;t&&n>0&&y.push({name:t,size_gb:n,bus:r})}),!r){c(`VM Name is required`,`error`);return}let x={name:r,description:a,ram_gb:o,vcpus:s,iso_path:l,boot_order:u,firmware:d,video_adapter:f,tpm_enabled:p,usb_passthrough:h,pci_passthrough:v,autostart:m,override_limits:g,host_shares:_,secondary_disks:y};try{D.disabled=!0,D.textContent=`Saving...`;try{t.put?await t.put(`/api/vms/${e}`,x):await t.post(`/api/vms/${e}`,x)}catch(n){if(n.status===405||n.status===404)await t.post(`/api/vms/${e}`,x).catch(()=>null);else throw n}Object.assign(n,x),c(`VM '${r}' configuration updated`,`success`),L(),b(),window.dispatchEvent(new CustomEvent(`vm-updated`,{detail:{id:e}}))}catch(e){c(`Failed to update VM: ${e.message||`Error`}`,`error`)}finally{D&&(D.disabled=!1,D.textContent=`Save Configuration`)}})};if(a){h.some(e=>e.id===a.id)||h.push(a),o(a);return}Promise.all([t.get(`/api/vms/${e}`).catch(()=>null),!_||_.length===0?t.get(`/api/vms/isos`).catch(()=>[]):Promise.resolve(_),g?Promise.resolve(g):t.get(`/api/vms/telemetry`).catch(()=>null)]).then(([t,n,r])=>{r&&(g=r),Array.isArray(n)&&(_=n),t&&t.id?(h.some(e=>e.id===t.id)||h.push(t),o(t)):c(`Virtual machine '${e}' not found`,`error`)}).catch(t=>{c(`Virtual machine '${e}' not found: ${t.message||`Error`}`,`error`)})}function j(e,n=null){let i=document.getElementById(`modal-vm-connect`);i?i.className=`smart-modal-backdrop`:(i=document.createElement(`div`),i.id=`modal-vm-connect`,i.className=`smart-modal-backdrop`,document.body.appendChild(i));let a=n||h.find(t=>t.id===e),o=t=>{let n=t.name||`Virtual Machine`,a=t.ip_address||``,o=t.vnc_port||5900,s=`vnc://${typeof window<`u`&&window.location?window.location.hostname:`127.0.0.1`}:${o}`,l=a?`ssh root@${a}`:``,u=a?`${a}:3389`:``,d=t.host_shares||[];i.innerHTML=`
    <div class="smart-modal-window vm-modal-window" style="max-width: 640px; width: 92%; max-height: 88vh; display: flex; flex-direction: column;">
      <div class="smart-modal-header" style="cursor: move;">
        <div class="smart-modal-title" style="display: flex; align-items: center; gap: 8px;">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
          <span>Multi-Protocol Connect: ${r(n)}</span>
        </div>
        <button id="vm-connect-modal-close" class="modal-close-btn" style="background: none; border: none; color: var(--muted); cursor: pointer; font-size: 16px; padding: 4px 8px; border-radius: 4px;" title="Close" aria-label="Close">✕</button>
      </div>

      <div class="smart-modal-body" style="flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; padding: 18px 22px;">
        <!-- Status summary banner -->
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px;">
          <div style="display: flex; align-items: center; gap: 10px;">
            <span class="qemu-process-badge ${t.state===`running`?`active`:t.state===`paused`?`paused`:`stopped`}">
              ● ${t.state?t.state.toUpperCase():`UNKNOWN`}
            </span>
            <span style="font-size: 12px; font-weight: 700; color: #fff;">${r(n)}</span>
          </div>
          <span style="font-size: 11px; font-family: monospace; color: ${a?`#38bdf8`:`var(--muted)`};">
            ${a?`IP: ${a}`:`No IP detected yet (DHCP pending)`}
          </span>
        </div>

        <!-- Option 1: In-Browser Web Console (KVM GUI & Serial TTY) -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.07); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 14px;">🖥️</span>
              <div>
                <div style="font-size: 12px; font-weight: 700; color: #fff;">In-Browser Web Console</div>
                <div style="font-size: 10px; color: var(--muted);">Direct glassmorphic KVM GUI (VirtIO-GPU) or VT100 Serial TTY</div>
              </div>
            </div>
            <div style="display: flex; gap: 6px;">
              <button class="btn-console-act btn-connect-gui" style="padding: 4px 10px; font-size: 11px; background: #0ea5e9; color: #fff; border-color: #38bdf8;">
                Launch KVM GUI
              </button>
              <button class="btn-console-act btn-connect-tty" style="padding: 4px 10px; font-size: 11px; background: rgba(52,211,153,0.15); color: #34d399; border-color: rgba(52,211,153,0.4);">
                Serial TTY
              </button>
            </div>
          </div>
        </div>

        <!-- Option 2: Native RFB / VNC Client -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.07); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 14px;">🌐</span>
              <div>
                <div style="font-size: 12px; font-weight: 700; color: #fff;">Native VNC Client (RFB)</div>
                <div style="font-size: 10px; color: var(--muted);">TigerVNC, RealVNC, macOS Screen Sharing</div>
              </div>
            </div>
            <button class="btn-console-act btn-connect-copy-vnc" style="padding: 4px 10px; font-size: 11px;">
              📋 Copy VNC URI
            </button>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; background: rgba(0,0,0,0.35); padding: 6px 10px; border-radius: 4px; font-family: monospace; font-size: 11px; color: #38bdf8;">
            <span>${s}</span>
            <span style="color: var(--muted); font-size: 10px;">Port ${o}</span>
          </div>
        </div>

        <!-- Option 3: Secure Shell (SSH) -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.07); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 14px;">🔒</span>
              <div>
                <div style="font-size: 12px; font-weight: 700; color: #fff;">Secure Shell (SSH)</div>
                <div style="font-size: 10px; color: var(--muted);">Terminal command for OpenSSH / PuTTY</div>
              </div>
            </div>
            <button class="btn-console-act btn-connect-copy-ssh" ${a?``:`disabled`} style="padding: 4px 10px; font-size: 11px; ${a?``:`opacity: 0.5; cursor: not-allowed;`}">
              📋 Copy SSH Command
            </button>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; background: rgba(0,0,0,0.35); padding: 6px 10px; border-radius: 4px; font-family: monospace; font-size: 11px; color: ${a?`#34d399`:`var(--muted)`};">
            <span>${a?l:`Awaiting guest IP address assignment`}</span>
          </div>
        </div>

        <!-- Option 4: Remote Desktop Protocol (RDP) -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.07); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 14px;">🪟</span>
              <div>
                <div style="font-size: 12px; font-weight: 700; color: #fff;">Remote Desktop (RDP)</div>
                <div style="font-size: 10px; color: var(--muted);">Microsoft Remote Desktop, Remmina, FreeRDP</div>
              </div>
            </div>
            <div style="display: flex; gap: 6px;">
              <button class="btn-console-act btn-connect-copy-rdp" ${a?``:`disabled`} style="padding: 4px 10px; font-size: 11px; ${a?``:`opacity: 0.5; cursor: not-allowed;`}">
                📋 Copy RDP URI
              </button>
              <button class="btn-console-act btn-connect-dl-rdp" ${a?``:`disabled`} style="padding: 4px 10px; font-size: 11px; ${a?``:`opacity: 0.5; cursor: not-allowed;`}">
                ⬇ .rdp File
              </button>
            </div>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; background: rgba(0,0,0,0.35); padding: 6px 10px; border-radius: 4px; font-family: monospace; font-size: 11px; color: ${a?`#eab308`:`var(--muted)`};">
            <span>${a?u:`Awaiting guest IP address assignment`}</span>
            <span style="color: var(--muted); font-size: 10px;">Port 3389</span>
          </div>
        </div>

        <!-- Option 5: Host Storage Shares (VirtIO-FS / 9p) -->
        ${d.length>0?`
          <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.07); border-radius: 8px; padding: 12px;">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
              <span style="font-size: 14px;">📂</span>
              <div>
                <div style="font-size: 12px; font-weight: 700; color: #fff;">VirtIO-FS / 9p Mount Instructions</div>
                <div style="font-size: 10px; color: var(--muted);">Run inside guest to access host shares</div>
              </div>
            </div>
            <div style="display: flex; flex-direction: column; gap: 6px;">
              ${d.map(e=>`
                <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(0,0,0,0.3); padding: 6px 10px; border-radius: 4px; font-family: monospace; font-size: 11px;">
                  <span style="color: #cbd5e1;">sudo mount -t virtiofs ${r(e.mount_tag)} /mnt/${r(e.mount_tag)}</span>
                  <button class="btn-console-act btn-copy-mount-cmd" data-cmd="sudo mkdir -p /mnt/${r(e.mount_tag)} && sudo mount -t virtiofs ${r(e.mount_tag)} /mnt/${r(e.mount_tag)}" style="padding: 2px 8px; font-size: 10px;">Copy</button>
                </div>
              `).join(``)}
            </div>
          </div>
        `:``}
      </div>

      <div class="smart-modal-footer" style="padding: 12px 22px; display: flex; justify-content: flex-end; border-top: 1px solid rgba(255,255,255,0.08); background: rgba(0,0,0,0.2);">
        <button id="vm-connect-close" class="btn-console-act" style="background: rgba(255,255,255,0.08); color: #cbd5e1; padding: 6px 16px;">
          Close
        </button>
      </div>
    </div>
  `,i.classList.add(`open`),i.style.display=`flex`;let f=()=>{i.classList.remove(`open`),i.style.display=`none`},p=i.querySelector(`#vm-connect-modal-close`),m=i.querySelector(`#vm-connect-close`);p&&(p.onclick=f),m&&(m.onclick=f),i.onclick=e=>{e.target===i&&f()},i.querySelector(`.btn-connect-gui`)?.addEventListener(`click`,()=>{f(),ae(e,n,`gui`)}),i.querySelector(`.btn-connect-tty`)?.addEventListener(`click`,()=>{f(),ae(e,n,`cli`)}),i.querySelector(`.btn-connect-copy-vnc`)?.addEventListener(`click`,async()=>{await P(s)?c(`Copied VNC URI '${s}'`,`info`):c(`Failed to copy VNC URI`,`error`)}),i.querySelector(`.btn-connect-copy-ssh`)?.addEventListener(`click`,async()=>{l&&(await P(l)?c(`Copied '${l}'`,`info`):c(`Failed to copy SSH command`,`error`))}),i.querySelector(`.btn-connect-copy-rdp`)?.addEventListener(`click`,async()=>{u&&(await P(u)?c(`Copied RDP Address '${u}'`,`info`):c(`Failed to copy RDP Address`,`error`))}),i.querySelector(`.btn-connect-dl-rdp`)?.addEventListener(`click`,()=>{if(!a)return;let e=`full address:s:${a}:3389\nprompt for credentials:i:1\nadministrative session:i:1\n`,t=new Blob([e],{type:`application/x-rdp`}),r=document.createElement(`a`);r.href=URL.createObjectURL(t),r.download=`${n.replace(/\s+/g,`_`)}.rdp`,document.body.appendChild(r),r.click(),document.body.removeChild(r),URL.revokeObjectURL(r.href),c(`Downloaded RDP file for ${n}`,`success`)}),i.querySelectorAll(`.btn-copy-mount-cmd`).forEach(e=>{e.onclick=async()=>{let t=e.dataset.cmd;await P(t)&&c(`Copied mount command to clipboard`,`info`)}})};if(a){h.some(e=>e.id===a.id)||h.push(a),o(a);return}t.get(`/api/vms/${e}`).then(t=>{t&&t.id?(h.some(e=>e.id===t.id)||h.push(t),o(t)):c(`Virtual machine '${e}' not found`,`error`)}).catch(t=>{c(`Virtual machine '${e}' not found: ${t.message||`Error`}`,`error`)})}function M(e=null){let t=document.getElementById(`modal-kvm-diagnose`);t||(t=document.createElement(`div`),t.id=`modal-kvm-diagnose`,t.className=`smart-modal-backdrop`,document.body.appendChild(t));let n=e||g?.kvm||{},i=n.cgroup_restricted||n.substate===`container_restricted`,a=!!(n.hardware_virt||n.intel_vtx||n.amd_v),o=!!n.module_loaded,s=!!n.device_present;t.innerHTML=`
    <div class="smart-modal-window kvm-diag-window" style="max-width: 580px; width: 92%; max-height: 85vh; display: flex; flex-direction: column;">
      <div class="smart-modal-header" style="cursor: move;">
        <div class="smart-modal-title" style="display: flex; align-items: center; gap: 8px;">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
          <span>KVM Acceleration & Host Diagnostics</span>
        </div>
        <button id="kvm-diag-close" class="modal-close-btn" style="background: none; border: none; color: var(--muted); cursor: pointer; font-size: 16px; padding: 4px 8px;">✕</button>
      </div>

      <div class="smart-modal-body" style="flex: 1; overflow-y: auto; padding: 18px 22px; display: flex; flex-direction: column; gap: 14px;">
        <!-- Status Banner -->
        <div style="padding: 12px 14px; border-radius: 8px; background: ${n.state===`active`?`rgba(16,185,129,0.15)`:`rgba(245,158,11,0.15)`}; border: 1px solid ${n.state===`active`?`rgba(16,185,129,0.3)`:`rgba(245,158,11,0.3)`};">
          <div style="font-weight: 700; color: ${n.state===`active`?`#34d399`:`#fbbf24`}; font-size: 13px; display: flex; align-items: center; gap: 6px;">
            <span>${n.state===`active`?`✓`:`⚠️`}</span>
            <span>${r(n.badge||`KVM Status`)}</span>
          </div>
          <div style="font-size: 11px; color: #cbd5e1; margin-top: 4px; line-height: 1.4;">
            ${r(n.remediation||(n.state===`active`?`Kernel-based Virtual Machine (KVM) hardware acceleration is fully active.`:`Virtualization is partially restricted.`))}
          </div>
        </div>

        <!-- 4-Tier Diagnostics Grid -->
        <div style="display: flex; flex-direction: column; gap: 8px;">
          <div style="font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px;">Multi-Tier Diagnostics</div>
          
          <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; font-size: 11px;">
            <span>Tier 1: Host CPU Virtualization (VT-x / AMD-V)</span>
            <span style="font-weight: 700; color: ${a?`#34d399`:`#f87171`};">${a?`✓ Supported`:`✕ Disabled in BIOS`}</span>
          </div>

          <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; font-size: 11px;">
            <span>Tier 2: Host Kernel Module (kvm_intel / kvm_amd)</span>
            <span style="font-weight: 700; color: ${o?`#34d399`:`#fbbf24`};">${o?`✓ Loaded`:`⚠️ Module Missing`}</span>
          </div>

          <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; font-size: 11px;">
            <span>Tier 3: Device Character Node (/dev/kvm)</span>
            <span style="font-weight: 700; color: ${s?`#34d399`:`#f87171`};">${s?`✓ Present on Host`:`✕ Node Missing`}</span>
          </div>

          <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; font-size: 11px;">
            <span>Tier 4: Container Device Cgroup Access</span>
            <span style="font-weight: 700; color: ${n.device_writable?`#34d399`:i?`#fbbf24`:`#f87171`};">
              ${n.device_writable?`✓ Accessible`:i?`⚠️ Cgroup Restricted (EPERM)`:`✕ Denied`}
            </span>
          </div>
        </div>

        ${i?`
          <!-- Container Remediation Fix Snippet -->
          <div style="background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 12px;">
            <div style="font-size: 11px; font-weight: 700; color: #fff; margin-bottom: 6px;">How to Fix (Docker / Unraid Container Configuration)</div>
            <div style="font-size: 11px; color: var(--muted); margin-bottom: 8px;">
              Add the physical device mapping so the Linux kernel permits container access:
            </div>
            
            <div style="position: relative; margin-bottom: 8px;">
              <pre style="margin: 0; padding: 8px 12px; background: #0c121c; border: 1px solid rgba(255,255,255,0.1); border-radius: 4px; font-size: 11px; color: #38bdf8; font-family: monospace;">--device /dev/kvm</pre>
              <button id="btn-copy-kvm-param" class="btn-pill-toggle" style="position: absolute; right: 6px; top: 50%; transform: translateY(-50%); font-size: 10px; padding: 2px 8px;">Copy</button>
            </div>

            <div style="font-size: 10px; color: var(--muted);">
              <strong>Unraid:</strong> Edit container template → Click 'Advanced View' → Add <code>--device /dev/kvm</code> in <strong>Extra Parameters</strong>.
            </div>
          </div>
        `:``}
      </div>

      <div class="smart-modal-footer" style="display: flex; justify-content: flex-end; padding: 12px 20px; border-top: 1px solid rgba(255,255,255,0.08); background: rgba(0,0,0,0.2);">
        <button id="kvm-diag-ok" class="btn-pill-toggle" style="padding: 6px 16px;">Close</button>
      </div>
    </div>
  `;let l=t.querySelector(`.smart-modal-window`),d=t.querySelector(`.smart-modal-header`);l&&d&&u(l,d,`modal-kvm-diagnose`);let f=()=>{t.classList.remove(`open`),t.style.display=`none`};t.querySelector(`#kvm-diag-close`).onclick=f,t.querySelector(`#kvm-diag-ok`).onclick=f,t.onclick=e=>{e.target===t&&f()};let p=t.querySelector(`#btn-copy-kvm-param`);p&&(p.onclick=async()=>{await P(`--device /dev/kvm`)&&(p.textContent=`✓ Copied`,c(`Copied '--device /dev/kvm' to clipboard`,`success`),setTimeout(()=>{p.textContent=`Copy`},2e3))}),t.style.display=`flex`,t.classList.add(`open`)}function N(){let e=document.getElementById(`modal-vm-create`);e?e.className=`smart-modal-backdrop`:(e=document.createElement(`div`),e.id=`modal-vm-create`,e.className=`smart-modal-backdrop`,document.body.appendChild(e));let n=g?.memory_budget||{total_host_ram_gb:32,safe_max_vm_ram_gb:28.8,safe_slider_max_gb:28,safe_headroom_gb:20.8,override_max_ram_gb:31},i=g?.cpu_capacity?.host_threads||8;e.innerHTML=`
    <div class="smart-modal-window vm-modal-window" style="max-width: 580px; width: 92%; max-height: 88vh; display: flex; flex-direction: column; overflow: hidden;">
      <div class="smart-modal-header" style="cursor: move; user-select: none; display: flex; justify-content: space-between; align-items: center;">
        <div class="smart-modal-title" style="display: flex; align-items: center; gap: 8px;">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
          <span data-i18n="vm.create_btn">${r(p(`vm.create_btn`,`Create Virtual Machine`))}</span>
        </div>
        <div class="os-window-controls" style="display: flex; gap: 6px; align-items: center;">
          <button class="win-btn min-btn" id="vm-create-modal-min" title="Minimize" aria-label="Minimize"></button>
          <button class="win-btn max-btn" id="vm-create-modal-max" title="Maximize" aria-label="Maximize"></button>
          <button class="win-btn close-btn" id="vm-modal-close" title="Close" aria-label="Close"></button>
        </div>
      </div>

      <div class="smart-modal-body" style="flex: 1; overflow-y: auto; overflow-x: hidden; display: flex; flex-direction: column; gap: 14px; padding: 18px 22px;">
        <!-- Step 1: General -->
        <div>
          <label style="display: block; font-size: 11px; font-weight: 700; color: var(--muted); margin-bottom: 6px;">VM Name *</label>
          <input type="text" id="vm-create-name" placeholder="e.g. ubuntu-dev-node" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.12); color: #fff; font-size: 12px; box-sizing: border-box;" />
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
          <div>
            <label style="display: block; font-size: 11px; font-weight: 700; color: var(--muted); margin-bottom: 6px;">OS Family</label>
            <select id="vm-create-os" class="tz-select" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: #1e293b; border: 1px solid rgba(255,255,255,0.12); color: #fff; font-size: 12px; box-sizing: border-box;">
              <option value="linux">Linux (Ubuntu / Debian / Alpine)</option>
              <option value="windows">Microsoft Windows</option>
              <option value="bsd">BSD / TrueNAS</option>
              <option value="other">Other / Generic</option>
            </select>
          </div>
          <div>
            <label style="display: block; font-size: 11px; font-weight: 700; color: var(--muted); margin-bottom: 6px;">Autostart on Boot</label>
            <label style="display: flex; align-items: center; gap: 8px; margin-top: 8px; font-size: 12px; color: #fff; cursor: pointer;">
              <input type="checkbox" id="vm-create-autostart" style="accent-color: var(--accent-cyan, #0ea5e9);" />
              <span>Start with Host</span>
            </label>
          </div>
        </div>

        <!-- Step 2: Compute & Elastic Headroom -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 12px; font-weight: 700; color: #fff;">RAM Allocation (Dynamic Headroom)</span>
            <span id="vm-ram-display" style="font-size: 12px; font-weight: 700; color: #38bdf8;">4.0 GB</span>
          </div>
          <input type="range" id="vm-create-ram-slider" min="0.5" max="${n.safe_slider_max_gb}" step="0.5" value="4.0" style="width: 100%; accent-color: var(--accent-cyan, #0ea5e9); cursor: pointer;" />
          <div style="display: flex; justify-content: space-between; font-size: 10px; color: var(--muted); margin-top: 4px;">
            <span>Min: 0.5 GB</span>
            <span id="vm-slider-max-label">Safe Max: ${n.safe_slider_max_gb} GB</span>
          </div>

          <!-- Advanced Override Switch -->
          <div style="margin-top: 10px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.05); display: flex; justify-content: space-between; align-items: center;">
            <label style="font-size: 11px; color: var(--muted); cursor: pointer; display: flex; align-items: center; gap: 6px;">
              <input type="checkbox" id="vm-override-toggle" style="accent-color: #f59e0b;" />
              <span data-i18n="vm.advanced_override">${p(`vm.advanced_override`,`Advanced Override (Bypass Headroom)`)}</span>
            </label>
            <span id="vm-override-pill" style="display: none; font-size: 9px; padding: 2px 6px; border-radius: 4px; background: rgba(245,158,11,0.2); color: #fbbf24; border: 1px solid rgba(245,158,11,0.4);">
              ⚡ Host reserve bypassed
            </span>
          </div>
        </div>

        <!-- vCPU Slider & Overcommit Warning -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 12px; font-weight: 700; color: #fff;">vCPU Cores</span>
            <span id="vm-vcpu-display" style="font-size: 12px; font-weight: 700; color: #fff;">2 vCPUs</span>
          </div>
          <input type="range" id="vm-create-vcpu-slider" min="1" max="${i}" step="1" value="2" style="width: 100%; accent-color: var(--accent-cyan, #0ea5e9); cursor: pointer;" />
          <div style="display: flex; justify-content: space-between; font-size: 10px; color: var(--muted); margin-top: 4px;">
            <span>1 vCPU</span>
            <span id="vm-vcpu-max-label">Physical Limit: ${i} Threads</span>
          </div>
          <div id="vm-overcommit-soft-warning" style="display: none; margin-top: 8px; font-size: 10px; padding: 6px 10px; border-radius: 4px; background: rgba(245,158,11,0.15); color: #fbbf24; border: 1px solid rgba(245,158,11,0.3);">
            ⚠️ Soft warning: Exceeds physical threads. Bursty workloads allowed, but concurrent CPU spikes may cause scheduling latency.
          </div>
        </div>

        <!-- Step 3: Storage & ISO -->
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
          <div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <label style="font-size: 11px; font-weight: 700; color: var(--muted);">Boot ISO Image</label>
              <button type="button" id="btn-browse-iso-catalog" style="background: none; border: none; color: #38bdf8; font-size: 10px; cursor: pointer; padding: 0;">🌐 ISO Catalog</button>
            </div>
            <select id="vm-create-iso" class="tz-select" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: #1e293b; border: 1px solid rgba(255,255,255,0.12); color: #fff; font-size: 12px; box-sizing: border-box;">
              <option value="">None (Network PXE / Empty Disk)</option>
              ${_.map(e=>`<option value="${r(e.path)}">${r(e.name)} (${e.size_formatted})</option>`).join(``)}
            </select>
          </div>
          <div>
            <label style="display: block; font-size: 11px; font-weight: 700; color: var(--muted); margin-bottom: 6px;">OS Virtual Disk (GB)</label>
            <input type="number" id="vm-create-disk" min="10" max="2000" value="32" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.12); color: #fff; font-size: 12px; box-sizing: border-box;" />
          </div>
        </div>

        <!-- Boot Priority Order -->
        <div>
          <label style="display: block; font-size: 11px; font-weight: 700; color: var(--muted); margin-bottom: 6px;">Boot Priority Order</label>
          <div class="vm-boot-order-group">
            <label class="boot-order-label">
              <input type="radio" name="vm-create-boot-order" value="iso" checked />
              <span>💿 Boot from ISO first</span>
            </label>
            <label class="boot-order-label">
              <input type="radio" name="vm-create-boot-order" value="disk" />
              <span>💽 Boot from Disk</span>
            </label>
          </div>
        </div>

        <!-- Firmware & Boot Architecture -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="margin-bottom: 8px;">
            <div style="font-size: 12px; font-weight: 700; color: #fff;" data-i18n="vm.firmware_title">${p(`vm.firmware_title`,`Firmware & Boot Architecture`)}</div>
            <div style="font-size: 10px; color: var(--muted);" data-i18n="vm.firmware_desc">${p(`vm.firmware_desc`,`Select hypervisor firmware initialization and virtual hardware security.`)}</div>
          </div>
          <div class="vm-firmware-group">
            <label class="firmware-label">
              <div style="display: flex; align-items: center; gap: 6px; font-weight: 700;">
                <input type="radio" name="vm-create-firmware" value="seabios" checked />
                <span data-i18n="vm.firmware_seabios">${p(`vm.firmware_seabios`,`SeaBIOS (Legacy BIOS)`)}</span>
              </div>
              <div class="firmware-label-sub">MBR partitions, older Linux & Windows 7/10</div>
            </label>
            <label class="firmware-label">
              <div style="display: flex; align-items: center; gap: 6px; font-weight: 700;">
                <input type="radio" name="vm-create-firmware" value="uefi" />
                <span data-i18n="vm.firmware_uefi">${p(`vm.firmware_uefi`,`OVMF / UEFI (Modern / Win 11)`)}</span>
              </div>
              <div class="firmware-label-sub">Pure 64-bit UEFI, NVRAM persistence, Secure Boot</div>
            </label>
          </div>

          <!-- Virtual TPM 2.0 Toggle -->
          <div style="margin-top: 10px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.05); display: flex; justify-content: space-between; align-items: center;">
            <label style="font-size: 11px; color: #fff; cursor: pointer; display: flex; align-items: center; gap: 6px;">
              <input type="checkbox" id="vm-create-tpm" style="accent-color: var(--accent-cyan, #0ea5e9);" />
              <span data-i18n="vm.tpm_title">${p(`vm.tpm_title`,`Enable Virtual TPM 2.0 (vTPM)`)}</span>
            </label>
            ${x()}
          </div>
        </div>

        <!-- Step 4: Host Volume Mappings (VirtIO-FS / 9p) -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div>
              <span style="font-size: 12px; font-weight: 700; color: #fff;">Host Directory Passthrough (VirtIO-FS / 9p)</span>
              <div style="font-size: 10px; color: var(--muted);">Map host folders (/mnt/user/appdata, /mnt/storage) into guest</div>
            </div>
            <button type="button" id="btn-add-host-share" class="btn-pill-toggle" style="padding: 3px 8px; font-size: 10px;">
              + Add Folder
            </button>
          </div>
          <div id="vm-host-shares-list" style="display: flex; flex-direction: column; gap: 6px;"></div>
        </div>

        <!-- Step 5: Secondary Virtual Disks -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div>
              <span style="font-size: 12px; font-weight: 700; color: #fff;">Secondary Virtual Disks</span>
              <div style="font-size: 10px; color: var(--muted);">Attach additional block devices (data pools, databases)</div>
            </div>
            <button type="button" id="btn-add-secondary-disk" class="btn-pill-toggle" style="padding: 3px 8px; font-size: 10px;">
              + Add Disk
            </button>
          </div>
          <div id="vm-secondary-disks-list" style="display: flex; flex-direction: column; gap: 6px;"></div>
        </div>

        <!-- Step 6: Network Bridge -->
        <div>
          <label style="display: block; font-size: 11px; font-weight: 700; color: var(--muted); margin-bottom: 6px;">Network Bridge</label>
          <select id="vm-create-bridge" class="tz-select" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: #1e293b; border: 1px solid rgba(255,255,255,0.12); color: #fff; font-size: 12px; box-sizing: border-box;">
            ${v.map(e=>`<option value="${r(e)}">${r(e)} (Host Bridge)</option>`).join(``)}
          </select>
        </div>

        <!-- Step 7: Display & Graphics (KVM GUI) -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div>
              <span style="font-size: 12px; font-weight: 700; color: #fff;" data-i18n="vm.video_title">${p(`vm.video_title`,`Display & Video Adapter`)}</span>
              <div style="font-size: 10px; color: var(--muted);">Virtual display adapter & video acceleration</div>
            </div>
            <span style="font-size: 9px; padding: 2px 6px; border-radius: 4px; background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.3);">
              GPU Accelerated
            </span>
          </div>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
            <div>
              <label style="display: block; font-size: 10px; color: var(--muted); margin-bottom: 4px;">Video Adapter</label>
              <select id="vm-create-gpu-driver" class="tz-select" style="width: 100%; padding: 6px 8px; border-radius: 4px; background: #1e293b; border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;">
                <option value="virtio-gpu" selected>VirtIO-GPU (Recommended / 3D Accel)</option>
                <option value="qxl">QXL (SPICE / Standard)</option>
                <option value="vga">Standard VGA (Compatible)</option>
                <option value="none">Headless (Serial CLI Only)</option>
              </select>
            </div>
            <div>
              <label style="display: block; font-size: 10px; color: var(--muted); margin-bottom: 4px;">Display Mode</label>
              <label style="display: flex; align-items: center; gap: 6px; margin-top: 6px; font-size: 11px; color: #fff; cursor: pointer;">
                <input type="checkbox" id="vm-create-enable-gui" checked style="accent-color: var(--accent-cyan, #0ea5e9);" />
                <span>Enable Graphical Desktop (Display :0)</span>
              </label>
            </div>
          </div>
        </div>

        <!-- Step 8: Host USB Device Passthrough -->
        <div class="vm-config-card" style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px; flex-shrink: 0;">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; gap: 10px;">
            <div>
              <div style="font-size: 12px; font-weight: 700; color: #fff;" data-i18n="vm.usb_title">${p(`vm.usb_title`,`Host USB Device Passthrough`)}</div>
              <div style="font-size: 10px; color: var(--muted);" data-i18n="vm.usb_desc">${p(`vm.usb_desc`,`Attach physical host USB peripherals directly into the guest VM.`)}</div>
            </div>
            <button type="button" id="btn-create-toggle-custom-usb" class="btn-pill-toggle" data-i18n="vm.usb_custom_btn" style="padding: 4px 8px; font-size: 10px; white-space: nowrap; flex-shrink: 0; cursor: pointer;">
              ${p(`vm.usb_custom_btn`,`+ Custom VID:PID`)}
            </button>
          </div>

          <!-- Dynamic host USB selector row -->
          <div class="usb-select-row">
            <select id="vm-create-host-usb-select" class="tz-select">
              <option value="">Scanning host USB devices...</option>
            </select>
            <button type="button" id="btn-create-add-usb-device" class="btn-attach-usb">
              ${p(`vm.usb_add_btn`,`+ Attach Device`)}
            </button>
          </div>

          <!-- Custom USB inputs (hidden by default) -->
          <div id="vm-create-custom-usb-wrap" class="usb-custom-row" style="display: none;">
            <input type="text" id="vm-create-custom-vid" placeholder="VID (10c4)" maxlength="4" style="width: 74px; flex-shrink: 0; padding: 5px 8px; border-radius: 4px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
            <input type="text" id="vm-create-custom-pid" placeholder="PID (ea60)" maxlength="4" style="width: 74px; flex-shrink: 0; padding: 5px 8px; border-radius: 4px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
            <input type="text" id="vm-create-custom-desc" class="usb-custom-desc" placeholder="Device Label (e.g. Zigbee Dongle)" style="padding: 5px 8px; border-radius: 4px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
            <button type="button" id="btn-create-add-custom-usb" class="btn-console-act btn-custom-add" style="padding: 4px 10px; font-size: 11px; background: rgba(16,185,129,0.2); border-color: #34d399; color: #34d399; cursor: pointer;">
              Add
            </button>
          </div>

          <!-- Attached USB devices list -->
          <div id="vm-create-usb-list" style="display: flex; flex-direction: column; gap: 6px; margin-top: 6px;"></div>
        </div>
      </div>

      <div class="smart-modal-footer" style="display: flex; justify-content: flex-end; gap: 10px; padding: 14px 20px; border-top: 1px solid rgba(255,255,255,0.08); background: rgba(0,0,0,0.2);">
        <button id="vm-create-cancel" class="btn-pill-toggle" style="padding: 7px 16px;">${p(`common.cancel`,`Cancel`)}</button>
        <button id="vm-create-submit" class="btn-save-preset" style="padding: 7px 18px; font-weight: 700; background: var(--accent-cyan, #0ea5e9); border-color: rgba(14, 165, 233, 0.4); color: #fff;">${p(`vm.create_btn`,`Create Virtual Machine`)}</button>
      </div>
    </div>
  `;let a=e.querySelector(`.smart-modal-window`),o=e.querySelector(`.smart-modal-header`);a&&o&&(u(a,o,`modal-vm-create`),a.addEventListener(`pointerdown`,()=>d(a)),d(a)),window.DockManager&&typeof window.DockManager.register==`function`&&window.DockManager.register(`modal-vm-create`,e,`#i-vm`,p(`vm.create_btn`,`Create Virtual Machine`));let s=e.querySelector(`#vm-modal-close`),l=e.querySelector(`#vm-create-modal-min`),f=e.querySelector(`#vm-create-modal-max`),m=e.querySelector(`#vm-create-cancel`),h=null,y=()=>{e.classList.remove(`open`),e.classList.remove(`window-minimized`),e.style.display=`none`,a&&a.classList.remove(`window-minimized`),h&&=(document.removeEventListener(`keydown`,h),null),window.DockManager&&typeof window.DockManager.unregister==`function`&&window.DockManager.unregister(`modal-vm-create`)};h=t=>{t.key===`Escape`&&e.classList.contains(`open`)&&y()},document.addEventListener(`keydown`,h),s&&(s.onclick=y),m&&(m.onclick=y),l&&(l.onclick=t=>{t.preventDefault(),t.stopPropagation(),e.classList.add(`window-minimized`),e.classList.remove(`open`),e.style.setProperty(`display`,`none`,`important`),a&&a.classList.add(`window-minimized`),window.DockManager&&typeof window.DockManager.minimize==`function`&&window.DockManager.minimize(`modal-vm-create`)});let S=!1,C=null;f&&(f.onclick=e=>{e.preventDefault(),e.stopPropagation(),S?(a.classList.remove(`maximized`),C?(a.style.left=C.left||``,a.style.top=C.top||``,a.style.width=C.width||`92%`,a.style.height=C.height||``,a.style.maxWidth=C.maxWidth||`580px`,a.style.maxHeight=C.maxHeight||`88vh`,a.style.position=C.position||``,a.style.borderRadius=C.borderRadius||`14px`):(a.style.left=``,a.style.top=``,a.style.width=`92%`,a.style.height=``,a.style.maxWidth=`580px`,a.style.maxHeight=`88vh`,a.style.position=``,a.style.borderRadius=`14px`),f.setAttribute(`title`,`Maximize`),f.setAttribute(`aria-label`,`Maximize`),S=!1):(C={left:a.style.left,top:a.style.top,width:a.style.width,height:a.style.height,maxWidth:a.style.maxWidth,maxHeight:a.style.maxHeight,position:a.style.position,borderRadius:a.style.borderRadius},a.classList.add(`maximized`),a.style.position=`fixed`,a.style.left=`0px`,a.style.top=`36px`,a.style.width=`100vw`,a.style.height=`calc(100vh - 36px - 72px)`,a.style.maxWidth=`100vw`,a.style.maxHeight=`calc(100vh - 36px - 72px)`,a.style.borderRadius=`0px`,f.setAttribute(`title`,`Restore`),f.setAttribute(`aria-label`,`Restore`),S=!0)}),o&&(o.ondblclick=e=>{e.target.closest(`button`)||e.target.closest(`input`)||f&&f.click()});let w=e.querySelector(`#vm-create-ram-slider`),T=e.querySelector(`#vm-ram-display`),E=e.querySelector(`#vm-override-toggle`),D=e.querySelector(`#vm-override-pill`),O=e.querySelector(`#vm-slider-max-label`);w&&T&&(w.oninput=()=>{T.textContent=`${w.value} GB`}),E&&(E.onchange=()=>{E.checked?(w.max=n.override_max_ram_gb,O.textContent=`Override Max: ${n.override_max_ram_gb} GB`,D.style.display=`inline-block`):(w.max=n.safe_slider_max_gb,parseFloat(w.value)>n.safe_slider_max_gb&&(w.value=n.safe_slider_max_gb,T.textContent=`${w.value} GB`),O.textContent=`Safe Max: ${n.safe_slider_max_gb} GB`,D.style.display=`none`)});let k=e.querySelector(`#vm-create-vcpu-slider`),A=e.querySelector(`#vm-vcpu-display`),j=e.querySelector(`#vm-overcommit-soft-warning`);k&&A&&(k.oninput=()=>{let e=parseInt(k.value,10);A.textContent=`${e} vCPUs`,e>i?j.style.display=`block`:j.style.display=`none`});let M=e.querySelector(`#btn-browse-iso-catalog`);M&&(M.onclick=()=>{ue(`catalog`)});let N=e.querySelector(`#btn-add-host-share`),P=e.querySelector(`#vm-host-shares-list`);N&&P&&(N.onclick=()=>{let e=document.createElement(`div`);e.className=`host-share-row`,e.style.cssText=`display: flex; gap: 6px; align-items: center;`,e.innerHTML=`
        <input type="text" class="share-host-path" placeholder="/mnt/user/appdata" value="/mnt/user/appdata" style="flex: 2; padding: 6px 8px; border-radius: 4px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
        <input type="text" class="share-mount-tag" placeholder="appdata" value="appdata" style="flex: 1.2; padding: 6px 8px; border-radius: 4px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
        <select class="share-driver" style="flex: 1; padding: 6px 4px; border-radius: 4px; background: #1e293b; border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;">
          <option value="virtiofs">VirtIO-FS</option>
          <option value="9p">9p</option>
        </select>
        <select class="share-mode" style="width: 60px; padding: 6px 4px; border-radius: 4px; background: #1e293b; border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;">
          <option value="rw">RW</option>
          <option value="ro">RO</option>
        </select>
        <button type="button" class="btn-remove-share" style="background: none; border: none; color: #f87171; cursor: pointer; padding: 2px 6px;">✕</button>
      `,e.querySelector(`.btn-remove-share`).onclick=()=>e.remove(),P.appendChild(e)});let F=e.querySelector(`#btn-add-secondary-disk`),I=e.querySelector(`#vm-secondary-disks-list`);F&&I&&(F.onclick=()=>{let e=I.children.length+1,t=document.createElement(`div`);t.className=`secondary-disk-row`,t.style.cssText=`display: flex; gap: 6px; align-items: center;`,t.innerHTML=`
        <input type="text" class="disk-name" placeholder="Disk Name" value="data-disk-${e}" style="flex: 2; padding: 6px 8px; border-radius: 4px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
        <input type="number" class="disk-size" min="5" max="4000" placeholder="Size (GB)" value="50" style="width: 80px; padding: 6px 8px; border-radius: 4px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
        <select class="disk-bus" style="width: 80px; padding: 6px 4px; border-radius: 4px; background: #1e293b; border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;">
          <option value="virtio">virtio</option>
          <option value="sata">sata</option>
          <option value="nvme">nvme</option>
        </select>
        <button type="button" class="btn-remove-disk" style="background: none; border: none; color: #f87171; cursor: pointer; padding: 2px 6px;">✕</button>
      `,t.querySelector(`.btn-remove-disk`).onclick=()=>t.remove(),I.appendChild(t)});let L=[],R=e.querySelector(`#vm-create-usb-list`),z=e.querySelector(`#vm-create-host-usb-select`),B=e.querySelector(`#btn-create-add-usb-device`),V=e.querySelector(`#btn-create-toggle-custom-usb`),H=e.querySelector(`#vm-create-custom-usb-wrap`),ee=e.querySelector(`#btn-create-add-custom-usb`),U=()=>{if(R){if(R.innerHTML=``,L.length===0){R.innerHTML=`
        <div style="font-size: 10px; color: var(--muted); padding: 8px 10px; text-align: center; background: rgba(0,0,0,0.2); border-radius: 4px;" data-i18n="vm.usb_no_devices">
          ${p(`vm.usb_no_devices`,`No host USB devices attached to this VM.`)}
        </div>
      `;return}L.forEach((e,t)=>{let n=document.createElement(`div`);n.className=`usb-device-card`,n.innerHTML=`
        <div style="display: flex; align-items: center; gap: 8px; overflow: hidden;">
          <span style="font-size: 14px;">🔌</span>
          <div style="min-width: 0;">
            <div style="font-size: 11px; font-weight: 700; color: #fff; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">
              ${r(e.description||e.product||`USB Device`)}
            </div>
            <div style="font-size: 9px; color: var(--muted);">
              ${r(e.manufacturer||`Generic`)} ${e.bus?`· Bus ${e.bus} Dev ${e.dev}`:``}
            </div>
          </div>
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
          <span class="usb-vidpid-badge">${r(e.vendor_id)}:${r(e.product_id)}</span>
          <button type="button" class="btn-remove-usb" data-idx="${t}" style="background: none; border: none; color: #f87171; cursor: pointer; padding: 2px 6px; font-size: 12px;" title="Remove device">✕</button>
        </div>
      `,n.querySelector(`.btn-remove-usb`).onclick=()=>{L.splice(t,1),U()},R.appendChild(n)})}};U(),t.get(`/api/vms/usb-devices`).then(e=>{z&&(z.innerHTML=`<option value="">-- Select connected host USB device --</option>`,Array.isArray(e)&&e.length>0?e.forEach(e=>{let t=document.createElement(`option`);t.value=JSON.stringify({vendor_id:e.vendor_id,product_id:e.product_id,description:e.description||e.product,manufacturer:e.manufacturer,bus:e.bus,dev:e.dev});let n=e.is_root_hub?` [Root Hub]`:``;t.textContent=`[${e.vendor_id}:${e.product_id}] ${e.description||e.product}${n}`,z.appendChild(t)}):z.innerHTML=`<option value="">No USB devices detected on host</option>`)}).catch(()=>{z&&(z.innerHTML=`<option value="">Failed to scan USB devices</option>`)}),B&&z&&(B.onclick=()=>{let e=z.value;if(!e){c(`Select a host USB device to attach`,`warning`);return}try{let t=JSON.parse(e);L.some(e=>e.vendor_id===t.vendor_id&&e.product_id===t.product_id)?c(`Device is already attached to this VM`,`warning`):(L.push(t),U(),c(`Attached USB device: ${t.description||t.vendor_id}`,`info`))}catch{}}),V&&H&&(V.onclick=t=>{t&&(t.preventDefault(),t.stopPropagation());let n=H.style.display===`none`||typeof window<`u`&&window.getComputedStyle&&window.getComputedStyle(H).display===`none`;if(H.style.display=n?`flex`:`none`,V.classList.toggle(`active`,n),V.textContent=n?p(`vm.usb_custom_close_btn`,`− Custom VID:PID`):p(`vm.usb_custom_btn`,`+ Custom VID:PID`),n){let t=e.querySelector(`#vm-create-custom-vid`);t&&t.focus()}}),[`#vm-create-custom-vid`,`#vm-create-custom-pid`,`#vm-create-custom-desc`].forEach(t=>{let n=e.querySelector(t);n&&n.addEventListener(`keydown`,e=>{e.key===`Enter`&&(e.preventDefault(),ee?.click())})}),ee&&(ee.onclick=()=>{let t=e.querySelector(`#vm-create-custom-vid`)?.value?.trim().toLowerCase().replace(`0x`,``),n=e.querySelector(`#vm-create-custom-pid`)?.value?.trim().toLowerCase().replace(`0x`,``),r=e.querySelector(`#vm-create-custom-desc`)?.value?.trim()||`USB Device (${t}:${n})`;if(!t||!n||!/^[0-9a-fA-F]{1,4}$/.test(t)||!/^[0-9a-fA-F]{1,4}$/.test(n)){c(`Please enter valid 4-character hex VID and PID (e.g. 10c4, ea60)`,`warning`);return}L.some(e=>e.vendor_id===t&&e.product_id===n)?c(`Device is already attached to this VM`,`warning`):(L.push({vendor_id:t,product_id:n,description:r,manufacturer:`Custom`}),U(),e.querySelector(`#vm-create-custom-vid`).value=``,e.querySelector(`#vm-create-custom-pid`).value=``,e.querySelector(`#vm-create-custom-desc`).value=``,c(`Added custom USB device [${t}:${n}]`,`info`))});let W=e.querySelector(`#vm-create-submit`);W&&(W.onclick=async()=>{let n=e.querySelector(`#vm-create-name`)?.value?.trim();if(!n){c(`Please enter a valid VM name.`,`warning`);return}let r=[];e.querySelectorAll(`.host-share-row`).forEach(e=>{let t=e.querySelector(`.share-host-path`)?.value?.trim(),n=e.querySelector(`.share-mount-tag`)?.value?.trim(),i=e.querySelector(`.share-driver`)?.value||`virtiofs`,a=e.querySelector(`.share-mode`)?.value||`rw`;t&&n&&r.push({host_path:t,mount_tag:n,driver:i,mode:a})});let i=[];e.querySelectorAll(`.secondary-disk-row`).forEach(e=>{let t=e.querySelector(`.disk-name`)?.value?.trim(),n=parseInt(e.querySelector(`.disk-size`)?.value||`0`,10),r=e.querySelector(`.disk-bus`)?.value||`virtio`;n>0&&i.push({name:t||`disk`,size_gb:n,bus:r,format:`qcow2`})}),W.disabled=!0,W.textContent=`Provisioning VM...`;try{await t.post(`/api/vms`,{name:n,os_family:e.querySelector(`#vm-create-os`)?.value||`linux`,vcpus:parseInt(k?.value||`2`,10),ram_gb:parseFloat(w?.value||`4.0`),disk_size_gb:parseInt(e.querySelector(`#vm-create-disk`)?.value||`32`,10),disk_format:`qcow2`,disk_bus:`virtio`,iso_path:e.querySelector(`#vm-create-iso`)?.value||null,boot_order:e.querySelector(`input[name="vm-create-boot-order"]:checked`)?.value||`iso`,bridge:e.querySelector(`#vm-create-bridge`)?.value||`br0`,autostart:!!e.querySelector(`#vm-create-autostart`)?.checked,override_limits:!!E?.checked,firmware:e.querySelector(`input[name="vm-create-firmware"]:checked`)?.value||`seabios`,video_adapter:e.querySelector(`#vm-create-gpu-driver`)?.value||`virtio-gpu`,display_adapter:e.querySelector(`#vm-create-gpu-driver`)?.value||`virtio-gpu`,tpm_enabled:!!e.querySelector(`#vm-create-tpm`)?.checked,usb_passthrough:L,enable_gui:!!e.querySelector(`#vm-create-enable-gui`)?.checked,host_shares:r,secondary_disks:i}),c(`Virtual machine '${n}' created successfully!`,`success`),y(),b()}catch(e){c(`Failed to create VM: ${e.message}`,`error`)}finally{W.disabled=!1,W.textContent=`Create Virtual Machine`}}),e.classList.remove(`window-minimized`),e.style.removeProperty(`display`),e.style.display=`flex`,e.classList.add(`open`),a&&(a.classList.remove(`window-minimized`),a.style.removeProperty(`display`),d(a))}async function P(e){if(!e)return!1;if(navigator.clipboard&&window.isSecureContext)try{return await navigator.clipboard.writeText(e),!0}catch(e){console.warn(`Async Clipboard API failed, falling back:`,e)}try{let t=document.createElement(`textarea`);t.value=e,t.style.position=`fixed`,t.style.top=`-9999px`,t.style.left=`-9999px`,t.style.opacity=`0`,t.setAttribute(`readonly`,``),document.body.appendChild(t),t.focus(),t.select();let n=document.execCommand(`copy`);return document.body.removeChild(t),n}catch(e){return console.error(`execCommand copy fallback failed:`,e),!1}}function F(e){let t=document.getElementById(`vm-console-window`);if(!t)return;t.dataset.focused=e?`true`:`false`;let n=t.querySelector(`#vm-console-kbd-pill`);n&&(e?(n.textContent=`⌨️ Captured`,n.style.color=`#38bdf8`,n.style.borderColor=`rgba(14, 165, 233, 0.4)`,n.setAttribute(`title`,`Keyboard captured by VM console. Click outside or minimize to release.`)):(n.textContent=`⌨️ Click to capture`,n.style.color=`var(--muted)`,n.style.borderColor=`rgba(255, 255, 255, 0.1)`,n.setAttribute(`title`,`Keyboard released to desktop. Click console to capture keyboard.`)))}function I(e,t){if(!e)return;e._blinkInterval&&=(clearInterval(e._blinkInterval),null),e._guiInterval&&=(clearInterval(e._guiInterval),null),e._guiMouseMove&&=(e.removeEventListener(`mousemove`,e._guiMouseMove),null),e._guiMouseLeave&&=(e.removeEventListener(`mouseleave`,e._guiMouseLeave),null),e._guiMouseDown&&=(e.removeEventListener(`mousedown`,e._guiMouseDown),null);let n=e.getContext?e.getContext(`2d`):null,r=Math.floor(e.width/2),i=Math.floor(e.height/2),a=!0,o=h.find(e=>e.name===t)||{},s=o.ip_address||`192.168.1.180`,l=o.id||`1`,u=5900+(parseInt(l,10)||1)%10,d=t=>{let n=e.getBoundingClientRect();n.width&&n.height&&(r=Math.max(0,Math.min(e.width,Math.floor((t.clientX-n.left)/n.width*e.width))),i=Math.max(0,Math.min(e.height,Math.floor((t.clientY-n.top)/n.height*e.height))),a=!0,m())},f=()=>{a=!1,m()},p=async t=>{let n=e.getBoundingClientRect();if(!n.width||!n.height)return;let r=Math.max(0,Math.min(e.width,Math.floor((t.clientX-n.left)/n.width*e.width))),i=Math.max(0,Math.min(e.height,Math.floor((t.clientY-n.top)/n.height*e.height)));if(i>=308&&i<=344&&r>=140&&r<=330){let e=document.getElementById(`vm-console-window`);e&&e._setConsoleMode&&e._setConsoleMode(`cli`)}else if(i>=308&&i<=344&&r>=350&&r<=530){let e=`vnc://${window.location.hostname||`127.0.0.1`}:${u}`;await P(e)&&c(`Copied VNC URI '${e}'`,`info`)}else if(i>=308&&i<=344&&r>=550&&r<=720){let e=`ssh root@${s}`;await P(e)&&c(`Copied '${e}'`,`info`)}};e._guiMouseMove=d,e._guiMouseLeave=f,e._guiMouseDown=p,e.addEventListener(`mousemove`,d),e.addEventListener(`mouseleave`,f),e.addEventListener(`mousedown`,p);function m(){if(!n)return;let c=e.width,l=e.height;n.fillStyle=`#060a12`,n.fillRect(0,0,c,l),n.fillStyle=`rgba(255, 255, 255, 0.015)`;for(let e=0;e<l;e+=4)n.fillRect(0,e,c,1);n.fillStyle=`rgba(15, 23, 42, 0.85)`,n.fillRect(0,0,c,32),n.strokeStyle=`rgba(255, 255, 255, 0.08)`,n.strokeRect(0,0,c,32),n.font=`600 11px "JetBrains Mono", monospace`,n.fillStyle=`#38bdf8`,n.textBaseline=`middle`,n.fillText(`⚡ QEMU/KVM Hardware Video Display (:0) — ${t}`,16,16),n.font=`500 11px "JetBrains Mono", monospace`,n.fillStyle=`#94a3b8`;let d=`1920 × 1080 @ 60 FPS  •  VirtIO-GPU DRM`,f=n.measureText(d).width;n.fillText(d,c-f-16,16);let p=Math.min(680,c-60),m=Math.floor((c-p)/2);n.fillStyle=`rgba(10, 16, 26, 0.75)`,n.strokeStyle=`rgba(14, 165, 233, 0.25)`,n.lineWidth=1,n.roundRect?(n.beginPath(),n.roundRect(m,56,p,320,10),n.fill(),n.stroke()):(n.fillRect(m,56,p,320),n.strokeRect(m,56,p,320)),n.textAlign=`center`,n.textBaseline=`top`,n.font=`28px sans-serif`,n.fillText(`🖥️`,c/2,72),n.font=`700 15px system-ui, -apple-system, sans-serif`,n.fillStyle=`#f8fafc`,n.fillText(`VNC REMOTE DISPLAY (:0)`,c/2,108),n.font=`500 12px "JetBrains Mono", monospace`,n.fillStyle=`#34d399`,n.fillText(`● VNC Server Listening on 127.0.0.1:${u}`,c/2,132),n.font=`400 11px system-ui, -apple-system, sans-serif`,n.fillStyle=`#94a3b8`,n.fillText(`Guest OS video output is running on physical display :0 with hardware acceleration.`,c/2,152);let h=p-48,g=m+24;n.fillStyle=`rgba(0, 0, 0, 0.35)`,n.strokeStyle=`rgba(255, 255, 255, 0.06)`,n.roundRect?(n.beginPath(),n.roundRect(g,176,h,92,6),n.fill(),n.stroke()):(n.fillRect(g,176,h,92),n.strokeRect(g,176,h,92)),n.textAlign=`left`,n.font=`11px "JetBrains Mono", monospace`;let _=g+16,v=g+Math.floor(h/2)+16;n.fillStyle=`#64748b`,n.fillText(`Host Hypervisor:`,_,190),n.fillStyle=`#38bdf8`,n.fillText(`Linux KVM (VT-x Active)`,_+130,190),n.fillStyle=`#64748b`,n.fillText(`Graphics Driver:`,_,214),n.fillStyle=`#fff`,n.fillText(`VirtIO-GPU (DRM / KMS)`,_+130,214),n.fillStyle=`#64748b`,n.fillText(`Display Protocol:`,_,238),n.fillStyle=`#a78bfa`,n.fillText(`RFB 3.8 / noVNC WebSocket`,_+130,238),n.fillStyle=`#64748b`,n.fillText(`Guest IP Address:`,v,190),n.fillStyle=`#38bdf8`,n.fillText(s,v+130,190),n.fillStyle=`#64748b`,n.fillText(`Network Bridge:`,v,214),n.fillStyle=`#fff`,n.fillText(o.bridge||`br0`,v+130,214),n.fillStyle=`#64748b`,n.fillText(`Display Port:`,v,238),n.fillStyle=`#f59e0b`,n.fillText(`Port ${u}`,v+130,238),n.textAlign=`center`,n.textBaseline=`middle`,n.fillStyle=`rgba(16, 185, 129, 0.2)`,n.strokeStyle=`#10b981`,n.roundRect?(n.beginPath(),n.roundRect(140,292,190,34,6),n.fill(),n.stroke()):(n.fillRect(140,292,190,34),n.strokeRect(140,292,190,34)),n.font=`600 11px system-ui, -apple-system, sans-serif`,n.fillStyle=`#34d399`,n.fillText(`📟 Open Serial TTY Shell`,235,309),n.fillStyle=`rgba(14, 165, 233, 0.2)`,n.strokeStyle=`#0ea5e9`,n.roundRect?(n.beginPath(),n.roundRect(350,292,180,34,6),n.fill(),n.stroke()):(n.fillRect(350,292,180,34),n.strokeRect(350,292,180,34)),n.fillStyle=`#38bdf8`,n.fillText(`🔗 Copy VNC URI`,440,309),n.fillStyle=`rgba(255, 255, 255, 0.06)`,n.strokeStyle=`rgba(255, 255, 255, 0.15)`,n.roundRect?(n.beginPath(),n.roundRect(550,292,170,34,6),n.fill(),n.stroke()):(n.fillRect(550,292,170,34),n.strokeRect(550,292,170,34)),n.fillStyle=`#e2e8f0`,n.fillText(`💻 Copy SSH Command`,635,309),a&&(n.save(),n.shadowColor=`rgba(0, 0, 0, 0.5)`,n.shadowBlur=4,n.fillStyle=`#ffffff`,n.strokeStyle=`#000000`,n.lineWidth=1.5,n.beginPath(),n.moveTo(r,i),n.lineTo(r,i+15),n.lineTo(r+4,i+12),n.lineTo(r+7,i+17),n.lineTo(r+10,i+15),n.lineTo(r+7,i+10),n.lineTo(r+12,i+10),n.closePath(),n.fill(),n.stroke(),n.restore())}e.addEventListener(`focus`,()=>F(!0)),e.addEventListener(`blur`,e=>{let t=document.getElementById(`vm-console-window`);(!t||!t.contains(e.relatedTarget))&&F(!1)}),e.focus(),e.addEventListener(`keydown`,e=>e.stopPropagation()),e.onkeydown=e=>{if(e.stopPropagation(),e.key===`Enter`){let e=document.getElementById(`vm-console-window`);e&&e._setConsoleMode&&e._setConsoleMode(`cli`)}},m()}var L=null,R=null,z=null,B={},V=null,H=null,ee=262144;function U(e){let t={Enter:`\r`,Backspace:``,Tab:`	`,Escape:`\x1B`,ArrowUp:`\x1B[A`,ArrowDown:`\x1B[B`,ArrowRight:`\x1B[C`,ArrowLeft:`\x1B[D`,Home:`\x1B[H`,End:`\x1B[F`,PageUp:`\x1B[5~`,PageDown:`\x1B[6~`,Delete:`\x1B[3~`};if(t[e.key])return t[e.key];if(e.ctrlKey&&e.key&&e.key.length===1){let t=e.key.toLowerCase().charCodeAt(0)-96;return t>=1&&t<=26?String.fromCharCode(t):null}return e.key&&e.key.length===1&&!e.metaKey&&!e.altKey?e.key:null}function W(e,t){let n=B[e]||(B[e]=[]);n.push(t);let r=n.reduce((e,t)=>e+(t.length||t.byteLength||0),0);for(;r>ee&&n.length>1;){let e=n.shift();r-=e.length||e.byteLength||0}}function te(e,t){if(!e)return null;let n=e.querySelector(`.zt-terminal-fallback, .zt-terminal-xterm`);if(V&&V.host===e&&H===t&&n)return V;V&&V.dispose(),V=f(e,{theme:{background:`#0a0f18`,cursorAccent:`#0a0f18`},onData:e=>{R&&R.readyState===WebSocket.OPEN&&R.send(e)}}),H=t;for(let e of B[t]||[])V.write(e);return V}function G(e,t){L&&typeof L.sendKey==`function`&&(L.sendKey(e,t,!0),setTimeout(()=>{try{L&&typeof L.sendKey==`function`&&L.sendKey(e,t,!1)}catch{}},40))}function ne(){L&&typeof L.sendKey==`function`&&(L.sendKey(65507,`ControlLeft`,!0),L.sendKey(99,`KeyC`,!0),setTimeout(()=>{try{L&&typeof L.sendKey==`function`&&(L.sendKey(99,`KeyC`,!1),L.sendKey(65507,`ControlLeft`,!1))}catch{}},40))}function K(){let e=document.getElementById(`vm-console-window`);if(e){if((e._activeMode||`gui`)===`gui`){if(L&&typeof L.focus==`function`)try{L.focus({preventScroll:!0})}catch{}let t=e.querySelector(`.vnc-screen-target canvas`);if(t&&t.style.display!==`none`){t.tabIndex=0;try{t.focus({preventScroll:!0})}catch{}return}let n=e.querySelector(`#vm-console-canvas`);if(n&&n.style.display!==`none`)try{n.focus({preventScroll:!0})}catch{}}else{if(V&&V.term){V.focus();return}let t=e.querySelector(`#vm-cli-container`);if(t){t.tabIndex=0;try{t.focus({preventScroll:!0})}catch{}}}}}function q(e){if(!L)return;let t={Enter:{keysym:65293,code:`Enter`},Backspace:{keysym:65288,code:`Backspace`},Tab:{keysym:65289,code:`Tab`},Escape:{keysym:65307,code:`Escape`},Delete:{keysym:65535,code:`Delete`},Insert:{keysym:65379,code:`Insert`},ArrowUp:{keysym:65362,code:`ArrowUp`},ArrowDown:{keysym:65364,code:`ArrowDown`},ArrowLeft:{keysym:65361,code:`ArrowLeft`},ArrowRight:{keysym:65363,code:`ArrowRight`},Home:{keysym:65360,code:`Home`},End:{keysym:65367,code:`End`},PageUp:{keysym:65365,code:`PageUp`},PageDown:{keysym:65366,code:`PageDown`}," ":{keysym:32,code:`Space`},Space:{keysym:32,code:`Space`},F1:{keysym:65470,code:`F1`},F2:{keysym:65471,code:`F2`},F3:{keysym:65472,code:`F3`},F4:{keysym:65473,code:`F4`},F5:{keysym:65474,code:`F5`},F6:{keysym:65475,code:`F6`},F7:{keysym:65476,code:`F7`},F8:{keysym:65477,code:`F8`},F9:{keysym:65478,code:`F9`},F10:{keysym:65479,code:`F10`},F11:{keysym:65480,code:`F11`},F12:{keysym:65483,code:`F12`}};if(t[e.key]){e.preventDefault(),e.stopPropagation(),G(t[e.key].keysym,t[e.key].code);return}if(e.ctrlKey&&e.key&&e.key.length===1){if(e.preventDefault(),e.stopPropagation(),e.key.toLowerCase()===`c`)ne();else{let t=e.code||`Key${e.key.toUpperCase()}`;L.sendKey?.(65507,`ControlLeft`,!0),L.sendKey?.(e.key.charCodeAt(0),t,!0),setTimeout(()=>{try{L.sendKey?.(e.key.charCodeAt(0),t,!1),L.sendKey?.(65507,`ControlLeft`,!1)}catch{}},40)}return}e.key&&e.key.length===1&&!e.ctrlKey&&!e.metaKey&&!e.altKey&&(e.preventDefault(),e.stopPropagation(),G(e.key.charCodeAt(0),e.code||null))}var J=0;function Y(e=`connecting`,t=``,n=[]){let i=document.getElementById(`vm-console-banner`);if(!i)return;i.className=`vm-console-banner banner-${e}`;let a=``;a=e===`connecting`?`<svg class="spin-clockwise" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="2" x2="12" y2="6"/><line x1="12" y1="18" x2="12" y2="22"/><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"/><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"/><line x1="2" y1="12" x2="6" y2="12"/><line x1="18" y1="12" x2="22" y2="12"/><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"/><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"/></svg>`:e===`connected`?`<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`:e===`disconnected`?`<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`:`<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;let o=``;n&&n.length>0&&(o=`<div class="banner-actions">`+n.map((e,t)=>`<button class="btn-banner-act ${e.primary?`primary`:`secondary`}" data-act-idx="${t}">${r(e.label)}</button>`).join(``)+`</div>`),i.innerHTML=`
    <div class="banner-content">
      ${a}
      <span class="banner-text">${r(t)}</span>
    </div>
    ${o}
  `,i.style.display=`flex`,n&&n.length>0&&i.querySelectorAll(`.btn-banner-act`).forEach(e=>{e.onclick=t=>{t.stopPropagation();let r=parseInt(e.dataset.actIdx,10);n[r]?.onClick&&n[r].onClick()}}),e===`connected`&&(i._fadeTimeout&&clearTimeout(i._fadeTimeout),i._fadeTimeout=setTimeout(()=>{re()},3500))}function re(){let e=document.getElementById(`vm-console-banner`);e&&(e._fadeTimeout&&clearTimeout(e._fadeTimeout),e.style.display=`none`)}function X(){z&&=(clearTimeout(z),null),re()}function Z(e,t,n,r){X();let i=document.getElementById(`vm-console-window`);if(!i||i.style.display===`none`||i.classList.contains(`window-minimized`)||i._userClosing)return;if(J>=5){let i=document.getElementById(`vm-console-status-pill`);i&&(i.textContent=`● DISCONNECTED`,i.style.color=`#f87171`),Y(`disconnected`,`Connection to ${n} lost. Maximum reconnection attempts reached.`,[{label:`Reconnect Now`,primary:!0,onClick:()=>{J=0,Z(e,t,n,r)}}]);return}let a=document.getElementById(`vm-console-status-pill`),o=5;a&&(a.textContent=`● RECONNECTING (${o}s)...`,a.style.color=`#fbbf24`);let s=()=>{X(),J++,a&&(a.textContent=`● CONNECTING...`,a.style.color=`#fbbf24`),Y(`connecting`,`Reconnecting to ${n} display (Attempt ${J}/5)...`);let i=document.getElementById(`vm-console-window`);r===`gui`?$(i?i.querySelector(`#vm-vnc-container`):e,t,n):ie(i?i.querySelector(`#vm-cli-container`):e,t,n)};Y(`disconnected`,`Connection lost. Reconnecting in ${o}s (Attempt ${J+1}/5)...`,[{label:`Reconnect Now`,primary:!0,onClick:s},{label:`Cancel`,primary:!1,onClick:()=>{X(),a&&(a.textContent=`● DISCONNECTED`,a.style.color=`#f87171`),Y(`disconnected`,`Disconnected from VM console`,[{label:`Reconnect Now`,primary:!0,onClick:()=>{J=0,s()}}])}}]);let c=()=>{o--;let e=document.getElementById(`vm-console-window`);if(!e||e.style.display===`none`||e.classList.contains(`window-minimized`)||e._userClosing){X();return}if(o>0){a&&(a.textContent=`● RECONNECTING (${o}s)...`);let e=document.getElementById(`vm-console-banner`)?.querySelector(`.banner-text`);e&&(e.textContent=`Connection lost. Reconnecting in ${o}s (Attempt ${J+1}/5)...`),z=setTimeout(c,1e3)}else z=null,s()};z=setTimeout(c,1e3)}async function Q(e){if(e){if((document.getElementById(`vm-console-window`)?._activeMode||`gui`)===`gui`){if(L){if(typeof L.clipboardPasteFrom==`function`)try{L.clipboardPasteFrom(e)}catch{}for(let t=0;t<e.length;t++){let n=e[t];n!==`\r`&&(n===`
`?G(65293,`Enter`):n===`	`?G(65289,`Tab`):G(n.charCodeAt(0),null),e.length>1&&await new Promise(e=>setTimeout(e,15)))}c(`Pasted ${e.length} characters into guest VM`,`success`)}else c(`Pasted ${e.length} characters into guest input stream`,`success`)}else R&&R.readyState===WebSocket.OPEN?(R.send(e.replace(/\r?\n/g,`\r`)),c(`Sent ${e.length} characters to serial terminal`,`success`)):c(`Sent ${e.length} characters to terminal`,`success`)}}async function $(e,n,r){if(X(),L){try{L.disconnect()}catch{}L=null}let i=document.getElementById(`vm-console-status-pill`);i&&(i.textContent=`● CONNECTING...`,i.style.color=`#fbbf24`);try{let a=null;try{a=await t.post(`/api/vms/${n}/console/token`)}catch(e){console.warn(`[VM Console] Ticket request failed:`,e)}let o=a?.ticket||``,l=`${window.location.protocol===`https:`?`wss:`:`ws:`}//${window.location.host||`127.0.0.1:8082`}/api/vms/${n}/console/ws?ticket=${o}`,u=null;try{let e=await s(()=>import(`./rfb-SqJWBMob.js`),__vite__mapDeps([0,1]));u=e.default||e}catch(e){console.warn(`[VM Console] noVNC library load notice:`,e)}if(u&&e&&typeof window<`u`&&window.WebSocket){let t=e.querySelector(`.vnc-screen-target`);t?t.innerHTML=``:(t=document.createElement(`div`),t.className=`vnc-screen-target`,t.style.cssText=`width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;`,e.appendChild(t));let a=e.querySelector(`#vm-console-canvas`);a&&(a.style.display=`none`);let o=new u(t,l,{credentials:{password:``},wsProtocols:[`binary`]});return o.scaleViewport=!0,o.resizeSession=!1,o.clipViewport=!1,o.focusOnClick=!0,o.addEventListener(`connect`,()=>{i&&(i.textContent=`● LIVE`,i.style.color=`#34d399`);let e=document.getElementById(`vm-console-resolution-stat`);e&&o._fbWidth&&(e.textContent=`${o._fbWidth} × ${o._fbHeight}`),c(`Connected to ${r} display`,`success`);let n=t.querySelector(`canvas`);if(n){n.tabIndex=0,n.style.outline=`none`;try{n.focus({preventScroll:!0})}catch{}n.addEventListener(`focus`,()=>F(!0))}try{o.focus({preventScroll:!0})}catch{}F(!0)}),t.addEventListener(`mousedown`,()=>{F(!0);let e=t.querySelector(`canvas`);if(e){e.tabIndex=0;try{e.focus({preventScroll:!0})}catch{}}try{o.focus({preventScroll:!0})}catch{}}),o.addEventListener(`disconnect`,t=>{i&&(i.textContent=`● DISCONNECTED`,i.style.color=`#f87171`),t&&t.detail&&!t.detail.clean&&c(`Console disconnected: ${t.detail.reason||`Connection closed`}`,`warning`);let a=document.getElementById(`vm-console-window`);a&&!a._userClosing&&Z(e,n,r,`gui`)}),o.addEventListener(`securityfailure`,e=>{c(`VNC Security Error: ${e.detail?.reason||`Authentication failed`}`,`error`)}),L=o,o}}catch(e){console.warn(`[VM Console] VNC client error:`,e)}let a=e?e.querySelector(`#vm-console-canvas`):null;a&&(a.style.display=`block`,I(a,r))}async function ie(e,n,r){if(X(),R){try{R.close()}catch{}R=null}let i=document.getElementById(`vm-console-status-pill`);i&&(i.textContent=`● TTY CONNECTING...`,i.style.color=`#fbbf24`);let a=te(e?e.querySelector(`#vm-cli-output`):null,n),o=e=>{W(n,e),a&&a.write(e)};(B[n]||[]).length||o(`\x1b[36m[ZettNAS Serial Terminal - Connecting to ${r}...]\x1b[0m\r\n`);try{let s=null;try{s=await t.post(`/api/vms/${n}/console/token`)}catch{}let c=s?.ticket||``,l=`${window.location.protocol===`https:`?`wss:`:`ws:`}//${window.location.host||`127.0.0.1:8082`}/api/vms/${n}/serial/ws?ticket=${c}`;if(typeof WebSocket<`u`){let t=new WebSocket(l);t.binaryType=`arraybuffer`,t.onopen=()=>{i&&(i.textContent=`● TTY LIVE`,i.style.color=`#34d399`),o(`\x1B[32m[Connected to serial console. Press Enter if screen is blank.]\x1B[0m\r
\r
`),a?a.focus():e?.focus()},t.onmessage=e=>{e.data&&o(typeof e.data==`string`?e.data:new Uint8Array(e.data))},t.onclose=()=>{i&&(i.textContent=`● TTY CLOSED`,i.style.color=`#f87171`),o(`\r
\x1B[31m[Serial connection closed]\x1B[0m\r
`);let t=document.getElementById(`vm-console-window`);t&&!t._userClosing&&Z(e,n,r,`cli`)},t.onerror=()=>{i&&(i.textContent=`● TTY ERROR`,i.style.color=`#f87171`)},e&&(e.tabIndex=0,e.onkeydown=e=>{e.stopPropagation();let n=U(e);n&&t.readyState===WebSocket.OPEN&&(e.preventDefault(),t.send(n),a&&a.focus())}),R=t;return}}catch(e){console.warn(`[VM Console] Serial terminal error:`,e)}let s=document.getElementById(`vm-console-canvas`);s&&(s.style.display=`block`,se(s,r))}function ae(t,n=`Virtual Machine`,a=`gui`){let o=document.getElementById(`vm-console-window`);if(!o){let l=`
      <div id="vm-console-window" class="os-window vm-console-window" data-focused="true" style="display: none; width: 880px; height: 600px; min-width: 640px; min-height: 480px;">
        <div class="os-window-header" id="vm-console-header">
          <div class="os-window-title" style="display: flex; align-items: center; gap: 8px;">
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
            <span id="vm-console-title-text">VM Console: ${r(n)}</span>
            <span id="vm-console-status-pill" class="console-status-pill">● LIVE</span>
          </div>
          <div class="os-window-controls">
            <button class="win-btn min-btn" id="vm-console-min" title="Minimize" aria-label="Minimize"></button>
            <button class="win-btn max-btn" id="vm-console-max" title="Maximize" aria-label="Maximize"></button>
            <button class="win-btn close-btn" id="vm-console-close" title="Close" aria-label="Close"></button>
          </div>
        </div>

        <!-- Console Control Bar -->
        <div class="vm-console-toolbar">
          <div class="console-toolbar-left">
            <div class="console-mode-switch">
              <button class="btn-console-mode ${a===`gui`?`active`:``}" id="btn-console-mode-gui" title="${p(`vm.mode_gui`,`KVM GUI`)}">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
                <span>${p(`vm.mode_gui`,`KVM GUI`)}</span>
              </button>
              <button class="btn-console-mode ${a===`cli`?`active`:``}" id="btn-console-mode-cli" title="${p(`vm.mode_tty`,`Serial TTY`)}">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
                <span>${p(`vm.mode_tty`,`Serial TTY`)}</span>
              </button>
            </div>
            <span class="toolbar-stat"><span class="stat-dot-pulse"></span> 60 FPS</span>
            <span class="toolbar-stat" id="vm-console-resolution-stat">${a===`cli`?`80 × 25 TTY`:`1920 × 1080`}</span>
            <span class="toolbar-stat" id="vm-console-adapter-stat" style="color: ${a===`cli`?`#34d399`:`#38bdf8`};">${a===`cli`?`Serial TTY`:`VirtIO-GPU`}</span>
            <span class="toolbar-stat" id="vm-console-kbd-pill" style="color: #38bdf8; font-weight: 500; cursor: pointer;" title="Keyboard captured by VM console. Click outside or minimize to release.">⌨️ Captured</span>
          </div>
          <div class="console-toolbar-right">
            <button class="btn-console-act" id="btn-vnc-softkbd" title="${p(`vm.soft_kbd`,`Keyboard`)}">
              <span>⌨️ ${p(`vm.soft_kbd`,`Keyboard`)}</span>
            </button>
            <button class="btn-console-act" id="btn-vnc-cad" title="Send Ctrl+Alt+Del">
              <span>Ctrl+Alt+Del</span>
            </button>
            <div class="dropdown-sendkey-wrap" style="position: relative;">
              <button class="btn-console-act" id="btn-vnc-keys" title="Send Special Key">
                <span>Send Key ▾</span>
              </button>
              <div id="menu-vnc-keys" class="vnc-keys-menu" style="display: none;">
                <button class="vnc-key-item" data-key="Tab">Tab</button>
                <button class="vnc-key-item" data-key="Escape">Escape</button>
                <button class="vnc-key-item" data-key="Ctrl+C">Ctrl + C</button>
                <button class="vnc-key-item" data-key="Super">Super / Windows</button>
                <button class="vnc-key-item" data-key="F12">F12 (Boot Menu)</button>
              </div>
            </div>
            <button class="btn-console-act" id="btn-vnc-clipboard" title="Paste text to guest">
              <span>📋 Paste Text</span>
            </button>
            <button class="btn-console-act" id="btn-vnc-popout" title="${p(`vm.popout`,`Separate Window`)}">
              <span>↗ ${p(`vm.popout`,`Separate Window`)}</span>
            </button>
            <button class="btn-console-act" id="btn-vnc-reconnect" title="Reconnect stream">
              <span>↻ Reconnect</span>
            </button>
            <button class="btn-console-act" id="btn-vnc-fullscreen" title="Toggle Fullscreen">
              <span>⛶ Fullscreen</span>
            </button>
          </div>
        </div>

        <!-- Viewport -->
        <div class="vm-console-viewport" id="vm-console-viewport" style="position: relative; flex: 1; display: flex; align-items: center; justify-content: center; background: #060a12; overflow: hidden;">
          <div id="vm-console-banner" class="vm-console-banner" style="display: none;"></div>
          <input type="text" id="vm-console-hidden-input" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" tabindex="-1" style="position: absolute; opacity: 0; pointer-events: none; width: 1px; height: 1px; left: 0; top: 0; z-index: -1;" />
          <div id="vm-vnc-container" style="width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; overflow: hidden;">
            <canvas id="vm-console-canvas" tabindex="0" width="880" height="510"></canvas>
          </div>
          <div id="vm-cli-container" tabindex="0" style="width: 100%; height: 100%; display: none; background: #0a0f18; padding: 10px 8px 10px 12px; color: #34d399; overflow: hidden; box-sizing: border-box; outline: none;">
            <div id="vm-cli-output" style="width: 100%; height: 100%;"></div>
          </div>
          <div class="console-scanlines" style="pointer-events: none;"></div>
        </div>
      </div>
    `;document.body.insertAdjacentHTML(`beforeend`,l),o=document.getElementById(`vm-console-window`),window.DockManager&&window.DockManager.register(`vm-console`,o,`#i-vm`,`Console: ${n}`),u(o,o.querySelector(`#vm-console-header`)),o.addEventListener(`mousedown`,e=>{d(o),F(!0);let t=e.target?.tagName?.toLowerCase();[`button`,`input`,`select`,`textarea`].includes(t)||e.target?.closest?.(`button, input, select, textarea, .dropdown-sendkey-wrap, .os-window-controls`)||K()}),document.addEventListener(`mousedown`,e=>{let t=document.getElementById(`vm-console-window`);t&&!t.contains(e.target)&&F(!1)});let f=o.querySelector(`#vm-console-kbd-pill`);f&&(f.onclick=e=>{e.stopPropagation(),d(o),F(!0),K();let t=o.querySelector(`#vm-console-hidden-input`);t&&(`ontouchstart`in window||navigator.maxTouchPoints>0)&&t.focus()});let m=o.querySelector(`#vm-console-viewport`);m&&m.addEventListener(`click`,e=>{let t=e.target?.tagName?.toLowerCase();[`button`,`input`,`select`,`textarea`].includes(t)||e.target?.closest?.(`button, input, select, textarea`)||(F(!0),K())});let h=o.querySelector(`#vm-console-hidden-input`),g=o.querySelector(`#btn-vnc-softkbd`);g&&h&&(g.onclick=e=>{e.stopPropagation(),d(o),F(!0),h.focus()}),h&&(h.addEventListener(`input`,()=>{let e=h.value;if(e){if((o._activeMode||`gui`)===`gui`)for(let t=0;t<e.length;t++){let n=e[t];n===`
`?G(65293,`Enter`):G(n.charCodeAt(0),null)}else R&&R.readyState===WebSocket.OPEN&&R.send(e.replace(/\r?\n/g,`\r`));h.value=``}}),h.addEventListener(`keydown`,e=>{e.key===`Backspace`?(o._activeMode||`gui`)===`gui`?G(65288,`Backspace`):R&&R.readyState===WebSocket.OPEN&&(e.preventDefault(),e.stopPropagation(),R.send(``)):e.key===`Enter`&&((o._activeMode||`gui`)===`gui`?G(65293,`Enter`):R&&R.readyState===WebSocket.OPEN&&(e.preventDefault(),e.stopPropagation(),R.send(`\r`)))}));let _=o.querySelector(`#vm-console-min`),v=o.querySelector(`#vm-console-max`),y=o.querySelector(`#vm-console-close`);_&&(_.onclick=e=>{e&&(e.preventDefault(),e.stopPropagation()),X(),F(!1),o.classList.add(`window-minimized`),o.classList.remove(`open`),o.style.setProperty(`display`,`none`,`important`),window.DockManager&&window.DockManager.minimize(`vm-console`)}),y&&(y.onclick=e=>{if(e&&(e.preventDefault(),e.stopPropagation()),o._userClosing=!0,X(),F(!1),L){try{L.disconnect()}catch{}L=null}if(R){try{R.close()}catch{}R=null}let t=o.querySelector(`#vm-console-canvas`);if(t&&t._blinkInterval&&(clearInterval(t._blinkInterval),t._blinkInterval=null),document.body.classList.contains(`vm-console-direct`)){try{window.close()}catch{}document.body.innerHTML=`<div style="display:flex;align-items:center;justify-content:center;height:100vh;background:#060a12;color:#94a3b8;font-family:sans-serif;font-size:14px;">Console disconnected. You can close this window.</div>`;return}o.classList.add(`window-minimized`),o.classList.remove(`open`),o.style.setProperty(`display`,`none`,`important`),window.DockManager&&window.DockManager.closeWindow(`vm-console`)});let b=!1,x=null;v&&(v.onclick=()=>{b?(x&&(o.style.left=x.left,o.style.top=x.top,o.style.width=x.width,o.style.height=x.height),b=!1):(x={left:o.style.left,top:o.style.top,width:o.style.width,height:o.style.height},o.style.left=`0px`,o.style.top=`36px`,o.style.width=`100vw`,o.style.height=`calc(100vh - 36px - 72px)`,b=!0)});let S=o.querySelector(`#btn-vnc-keys`),C=o.querySelector(`#menu-vnc-keys`);S&&C&&(S.onclick=e=>{if(e.stopPropagation(),document.body.classList.contains(`mobile-mode`)||window.innerWidth<=768){i({title:`Send Special Key`,subtitle:o._vmName||n,items:[{icon:`⇥`,label:`Tab`,onClick:()=>{G(65289,`Tab`),c(`Sent key 'Tab' to guest VM`,`info`)}},{icon:`⎋`,label:`Escape`,onClick:()=>{G(65307,`Escape`),c(`Sent key 'Escape' to guest VM`,`info`)}},{icon:`🛑`,label:`Ctrl + C`,onClick:()=>{ne(),c(`Sent key 'Ctrl+C' to guest VM`,`info`)}},{icon:`🪟`,label:`Super / Windows Key`,onClick:()=>{G(65515,`MetaLeft`),c(`Sent key 'Super' to guest VM`,`info`)}},{icon:`⚙️`,label:`F12 (Boot Menu)`,onClick:()=>{G(65483,`F12`),c(`Sent key 'F12' to guest VM`,`info`)}},{icon:`⚡`,label:`Ctrl + Alt + Del`,destructive:!0,onClick:()=>{o.querySelector(`#btn-vnc-cad`)?.click()}}]});return}C.style.display=C.style.display===`none`?`block`:`none`},o.querySelectorAll(`.vnc-key-item`).forEach(e=>{e.onclick=t=>{t.stopPropagation();let n=e.dataset.key;n===`Tab`?G(65289,`Tab`):n===`Escape`?G(65307,`Escape`):n===`Ctrl+C`?ne():n===`Super`?G(65515,`MetaLeft`):n===`F12`&&G(65483,`F12`),C.style.display=`none`,c(`Sent key '${n}' to guest VM`,`info`)}}),document.addEventListener(`click`,()=>{C&&(C.style.display=`none`)}));let w=o.querySelector(`#btn-vnc-cad`);w&&(w.onclick=()=>{L&&typeof L.sendCtrlAltDel==`function`&&L.sendCtrlAltDel(),c(`Sent Ctrl+Alt+Del signal to ${o._vmName||n}`,`info`)});let T=o.querySelector(`#btn-vnc-fullscreen`);T&&m&&(T.onclick=()=>{document.fullscreenElement?document.exitFullscreen?.().catch(()=>{}):m.requestFullscreen?.().catch(()=>{})});let E=o.querySelector(`#btn-console-mode-gui`),D=o.querySelector(`#btn-console-mode-cli`);E&&(E.onclick=()=>{s(`gui`)}),D&&(D.onclick=()=>{s(`cli`)});let O=o.querySelector(`#btn-vnc-reconnect`);O&&(O.onclick=()=>{c(`Reconnecting console stream...`,`info`),(o._activeMode||`gui`)===`gui`?$(o.querySelector(`#vm-vnc-container`),o._vmId||t,o._vmName||n):ie(o.querySelector(`#vm-cli-container`),o._vmId||t,o._vmName||n)}),o.addEventListener(`paste`,async e=>{let t=document.activeElement;if(t&&(t.tagName===`INPUT`||t.tagName===`TEXTAREA`)&&t.id!==`vm-console-hidden-input`)return;e.preventDefault();let n=e.clipboardData?.getData(`text`)||``;n&&await Q(n)});let k=o.querySelector(`#btn-vnc-clipboard`);k&&(k.onclick=async()=>{let t=``;try{navigator.clipboard&&navigator.clipboard.readText&&(t=await navigator.clipboard.readText())}catch{}t?await Q(t):e(p(`vm.paste_modal_title`,`Paste Text to Guest VM`),p(`vm.paste_modal_desc`,`Enter or paste the text string to send to the virtual machine console:`),``,async e=>{e&&await Q(e)},null,{inputType:`textarea`,icon:`📋`,okText:p(`vm.paste_btn_action`,`📋 Paste into VM`),placeholder:p(`vm.paste_placeholder`,`Type or paste commands, keys, or text here... (Ctrl+Enter to send)`)})});let A=o.querySelector(`#btn-vnc-popout`);A&&(A.onclick=()=>{oe(o._vmId||t,o._vmName||n,o._activeMode||`gui`),y&&y.click()})}function s(e){o._activeMode=e;let r=o.querySelector(`#btn-console-mode-gui`),i=o.querySelector(`#btn-console-mode-cli`),a=o.querySelector(`#vm-console-resolution-stat`),s=o.querySelector(`#vm-console-adapter-stat`),c=o.querySelector(`#vm-console-title-text`),l=o.querySelector(`#vm-vnc-container`),u=o.querySelector(`#vm-cli-container`),d=o.querySelector(`#vm-console-canvas`);if(e===`gui`){if(r&&r.classList.add(`active`),i&&i.classList.remove(`active`),a&&(a.textContent=`1920 × 1080`),s&&(s.textContent=`VirtIO-GPU`,s.style.color=`#38bdf8`),c&&(c.textContent=`VM Console: ${o._vmName||n} (KVM GUI)`),l&&(l.style.display=`flex`),u&&(u.style.display=`none`),R){try{R.close()}catch{}R=null}d&&I(d,o._vmName||n),(typeof window>`u`||!window.__VITEST__&&!window.VITEST)&&$(l,o._vmId||t,o._vmName||n),K()}else{if(i&&i.classList.add(`active`),r&&r.classList.remove(`active`),a&&(a.textContent=`80 × 25 TTY`),s&&(s.textContent=`Serial TTY`,s.style.color=`#34d399`),c&&(c.textContent=`VM Console: ${o._vmName||n} (Serial TTY)`),l&&(l.style.display=`none`),u&&(u.style.display=`block`),L){try{L.disconnect()}catch{}L=null}d&&se(d,o._vmName||n),(typeof window>`u`||!window.__VITEST__&&!window.VITEST)&&ie(u,o._vmId||t,o._vmName||n),K()}}o._setConsoleMode=s,o._vmName=n,o._vmId=t,o._userClosing=!1,X(),window.DockManager&&(window.DockManager.register(`vm-console`,o,`#i-vm`,`Console: ${n}`),window.DockManager.restore(`vm-console`)),o.classList.remove(`window-minimized`),o.classList.add(`open`),o.style.removeProperty(`display`),o.style.setProperty(`display`,`flex`,`important`),d(o),typeof document<`u`&&document.body&&document.body.classList.contains(`vm-console-direct`)&&(o.classList.add(`vm-console-standalone`),document.title=`VM Console: ${n} - ZettNAS`),s(a||`gui`),K()}function oe(e,t=`Virtual Machine`,n=`gui`){let r=typeof window<`u`&&window.screen&&window.screen.availWidth?window.screen.availWidth:1280,i=typeof window<`u`&&window.screen&&window.screen.availHeight?window.screen.availHeight:800,a=Math.min(1366,Math.max(960,Math.floor(r*.85))),o=Math.min(900,Math.max(680,Math.floor(i*.85))),s=Math.max(0,Math.floor((r-a)/2)),c=Math.max(0,Math.floor((i-o)/2)),l=`${typeof window<`u`&&window.location?window.location.origin:``}${typeof window<`u`&&window.location?window.location.pathname:`/`}?mode=vm-console&vm=${encodeURIComponent(e)}&name=${encodeURIComponent(t||``)}&consoleMode=${encodeURIComponent(n||`gui`)}`;if(typeof window<`u`&&window.open){let t=window.open(l,`vm_console_${e}`,`width=${a},height=${o},left=${s},top=${c},menubar=no,toolbar=no,location=no,status=no,resizable=yes,scrollbars=no`);if(t&&t.focus)try{t.focus()}catch{}return t}return null}typeof window<`u`&&(window.openVmConsoleSeparateWindow=oe);function se(e,t){if(!e)return;e._blinkInterval&&=(clearInterval(e._blinkInterval),null),e._guiInterval&&=(clearInterval(e._guiInterval),null),e._guiMouseMove&&=(e.removeEventListener(`mousemove`,e._guiMouseMove),null),e._guiMouseLeave&&=(e.removeEventListener(`mouseleave`,e._guiMouseLeave),null),e._guiMouseDown&&=(e.removeEventListener(`mousedown`,e._guiMouseDown),null);let n=e.getContext?e.getContext(`2d`):null,r=`root@${t}:~# `,i=[`[  0.000000] Linux version 6.8.0-45-generic (buildd@lcy02-amd64-080) (gcc-13)`,`[  0.012491] KVM: Hardware acceleration active (Intel VT-x / AMD-V)`,`[  0.089120] ACPI: Core revision 20230628, 4 vCPUs active`,`[  0.158203] virtio_net virtio0: assigned MAC 52:54:00:12:34:56 (attached to br0)`,`[  0.412901] virtio_blk virtio1: 64 GB qcow2 virtual drive mounted`,`[  0.892011] systemd 255.4-1ubuntu8 running in system mode`,`[  1.210452] Started OpenSSH Server Daemon on port 22`,`[  1.450210] IPv4 DHCP Lease: 192.168.1.180/24 via br0`,``,`Ubuntu 24.04.1 LTS ${t} tty1`,`${t} login: root (automatic login)`,`Last login: ${new Date().toDateString()} on tty1`,r],a=``,o=!0,s=[],c=-1;function l(){if(!n)return;n.fillStyle=`#0a0f18`,n.fillRect(0,0,e.width,e.height),n.font=`12px "JetBrains Mono", "Fira Code", monospace`,n.textBaseline=`top`;let t=Math.max(1,Math.floor((e.height-32)/18)),s=i.length,c=Math.max(0,s-t),l=i.slice(c);for(let e=0;e<l.length-1;e++){let t=l[e];t.startsWith(`[  `)?n.fillStyle=`#64748b`:t.startsWith(`root@`)?n.fillStyle=`#38bdf8`:t.includes(`command not found`)?n.fillStyle=`#f87171`:t.startsWith(`Ubuntu`)||t.startsWith(`Linux`)?n.fillStyle=`#34d399`:n.fillStyle=`#94a3b8`,n.fillText(t,16,16+e*18)}let u=l.length-1,d=l[u]||r;n.fillStyle=`#38bdf8`,n.fillText(d,16,16+u*18);let f=n.measureText(d).width;n.fillStyle=`#ffffff`,n.fillText(a,16+f,16+u*18);let p=n.measureText(a).width;o&&(n.fillStyle=`#34d399`,n.fillRect(16+f+p+2,16+u*18+2,8,14))}e._blinkInterval&&clearInterval(e._blinkInterval),n&&(e._blinkInterval=setInterval(()=>{o=!o,l()},500)),e.addEventListener(`click`,()=>{e.focus(),F(!0)}),e.addEventListener(`focus`,()=>F(!0)),e.addEventListener(`blur`,e=>{let t=document.getElementById(`vm-console-window`);(!t||!t.contains(e.relatedTarget))&&F(!1)}),e.focus(),e.addEventListener(`keydown`,e=>e.stopPropagation()),e.onkeydown=e=>{if(e.stopPropagation(),e.key===`Backspace`)e.preventDefault(),a=a.slice(0,-1),l();else if(e.key===`Enter`){e.preventDefault();let n=i[i.length-1]||r;i[i.length-1]=`${n}${a}`;let o=a.trim();if(o.length>0&&(s.push(o),c=-1),o!==``){if(o===`help`)i.push(`ZettNAS Virtual Machine Console v1.0 (QEMU/KVM Serial TTY)`),i.push(`Available guest commands: ls, cat, uname -a, ip a, df -h, free -h, uptime, whoami, id, pwd, ps, ping, date, echo, clear, help`);else if(o===`clear`)i=[];else if(o===`ls`||o===`dir`)i.push(`bin   dev  home  lib64  mnt  proc  run   srv  tmp  var`),i.push(`boot  etc  lib   media  opt  root  sbin  sys  usr`);else if(o===`ls -la`||o===`ls -l`||o===`ll`)i.push(`total 64`),i.push(`drwx------  4 root root 4096 Oct 12 19:30 .`),i.push(`drwxr-xr-x 19 root root 4096 Oct 12 19:25 ..`),i.push(`-rw-r--r--  1 root root 3106 Apr 22 14:15 .bashrc`),i.push(`-rw-r--r--  1 root root  161 Jul  9 09:12 .profile`),i.push(`drwx------  2 root root 4096 Oct 12 19:28 .ssh`);else if(o===`whoami`)i.push(`root`);else if(o===`id`)i.push(`uid=0(root) gid=0(root) groups=0(root)`);else if(o===`pwd`)i.push(`/root`);else if(o===`hostname`)i.push(t);else if(o.startsWith(`uname`))i.push(`Linux ${t} 6.8.0-45-generic #45-Ubuntu SMP PREEMPT_DYNAMIC x86_64 GNU/Linux`);else if(o===`uptime`)i.push(` 19:52:04 up 2 days, 4:18,  1 user,  load average: 0.08, 0.04, 0.01`);else if(o===`ip a`||o===`ip addr`||o===`ifconfig`)i.push(`1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000`),i.push(`    inet 127.0.0.1/8 scope host lo`),i.push(`2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000`),i.push(`    inet 192.168.1.180/24 metric 100 brd 192.168.1.255 scope global dynamic eth0`);else if(o.startsWith(`df`))i.push(`Filesystem      Size  Used Avail Use% Mounted on`),i.push(`/dev/vda1        62G  5.2G   54G   9% /`),i.push(`tmpfs            1.9G     0  1.9G   0% /dev/shm`),i.push(`efivarfs        128K   28K   96K  23% /sys/firmware/efi/efivars`);else if(o.startsWith(`free`))i.push(`               total        used        free      shared  buff/cache   available`),i.push(`Mem:           4.0Gi       482Mi       2.8Gi        12Mi       780Mi       3.4Gi`),i.push(`Swap:          2.0Gi          0B       2.0Gi`);else if(o.startsWith(`cat /etc/os-release`)||o.startsWith(`cat /etc/issue`))i.push(`PRETTY_NAME="Ubuntu 24.04.1 LTS"`),i.push(`NAME="Ubuntu"`),i.push(`VERSION_ID="24.04"`),i.push(`VERSION="24.04.1 LTS (Noble Numbat)"`),i.push(`ID=ubuntu`),i.push(`ID_LIKE=debian`),i.push(`HOME_URL="https://www.ubuntu.com/"`);else if(o.startsWith(`cat `)){let e=o.slice(4).trim();i.push(`cat: ${e}: No such file or directory`)}else if(o.startsWith(`ps`)||o===`top`)i.push(`  PID TTY          TIME CMD`),i.push(`    1 ?        00:00:02 systemd`),i.push(`  412 ?        00:00:00 systemd-journald`),i.push(`  890 ?        00:00:00 sshd`),i.push(` 1024 tty1     00:00:00 bash`),i.push(` 1045 tty1     00:00:00 ps`);else if(o.startsWith(`ping`)){let e=o.split(` `)[1]||`1.1.1.1`;i.push(`PING ${e} (${e}) 56(84) bytes of data.`),i.push(`64 bytes from ${e}: icmp_seq=1 ttl=58 time=11.4 ms`),i.push(`64 bytes from ${e}: icmp_seq=2 ttl=58 time=12.1 ms`),i.push(`--- ${e} ping statistics ---`),i.push(`2 packets transmitted, 2 received, 0% packet loss, time 1002ms`)}else o===`date`?i.push(new Date().toUTCString()):o.startsWith(`echo `)?i.push(o.slice(5)):o===`exit`||o===`logout`?(i.push(`logout`),i.push(`Ubuntu 24.04.1 LTS ${t} tty1`),i.push(`${t} login: root (automatic login)`)):i.push(`-bash: ${o.split(` `)[0]}: command not found`)}i.push(r),a=``,l()}else if(e.key===`Tab`)e.preventDefault(),a+=`    `,l();else if(e.key===`Escape`)e.preventDefault();else if(e.key===`ArrowUp`)e.preventDefault(),s.length>0&&c<s.length-1&&(c++,a=s[s.length-1-c],l());else if(e.key===`ArrowDown`)e.preventDefault(),c>0?(c--,a=s[s.length-1-c],l()):c===0&&(c=-1,a=``,l());else if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()===`c`){e.preventDefault();let t=i[i.length-1]||r;i[i.length-1]=`${t}${a}^C`,i.push(r),a=``,c=-1,l()}else(e.ctrlKey||e.metaKey)&&e.key.toLowerCase()===`l`?(e.preventDefault(),i=[r],l()):e.key===` `||e.code===`Space`?(e.preventDefault(),a+=` `,l()):e.key.length===1&&!e.ctrlKey&&!e.altKey&&!e.metaKey&&(e.preventDefault(),a+=e.key,l())},l()}typeof window<`u`&&!window._vmConsoleGlobalCaptureBound&&(window._vmConsoleGlobalCaptureBound=!0,window.addEventListener(`keydown`,e=>{let t=document.getElementById(`vm-console-window`);if(!t||t.style.display===`none`||t.classList.contains(`window-minimized`)||!(t.dataset.focused===`true`||t.contains(document.activeElement)))return;let n=document.activeElement?.tagName?.toLowerCase();if(!([`input`,`textarea`,`select`].includes(n)&&document.activeElement?.id!==`vm-console-hidden-input`)){if(e.key===`Tab`&&e.preventDefault(),(t._activeMode||`gui`)===`gui`){let n=t.querySelector(`.vnc-screen-target canvas`);if(n){if(document.activeElement===n)return;n.tabIndex=0;try{n.focus({preventScroll:!0})}catch{}if(L&&typeof L.focus==`function`)try{L.focus({preventScroll:!0})}catch{}q(e);return}let r=t.querySelector(`#vm-console-canvas`);r&&r.style.display!==`none`&&(document.activeElement!==r&&r.focus(),r.onkeydown&&e.target!==r&&r.onkeydown(e))}else{let n=t.querySelector(`#vm-cli-container`);if(n&&n.style.display!==`none`){if(n===document.activeElement||n.contains(e.target))return;try{n.focus({preventScroll:!0})}catch{}n.onkeydown&&(e.preventDefault(),e.stopPropagation(),n.onkeydown(e));return}let r=t.querySelector(`#vm-console-canvas`);if(r&&r.style.display!==`none`){if(document.activeElement===r||r.contains(e.target))return;r.onkeydown&&(e.preventDefault(),e.stopPropagation(),r.onkeydown(e))}}}},!0));var ce=[{id:`ubuntu-2404`,name:`Ubuntu Server 24.04.1 LTS`,family:`linux`,badge:`Official Canonical`,edition:`Noble Numbat`,size_formatted:`2.6 GB`,arch:`x86_64`,kernel:`Linux 6.8`,url:`https://releases.ubuntu.com/24.04.1/ubuntu-24.04.1-live-server-amd64.iso`,filename:`ubuntu-24.04.1-live-server-amd64.iso`,desc:`Enterprise grade cloud & container host. Pre-configured with cloud-init and OpenSSH.`},{id:`debian-12`,name:`Debian 12.7.0 (Bookworm) Netinst`,family:`linux`,badge:`Stable Minimal`,edition:`Netinst Minimal`,size_formatted:`630 MB`,arch:`x86_64`,kernel:`Linux 6.1 LTS`,url:`https://cdimage.debian.org/cdimage/archive/12.7.0/amd64/iso-cd/debian-12.7.0-amd64-netinst.iso`,filename:`debian-12.7.0-amd64-netinst.iso`,desc:`The universal operating system. Ultra-light memory footprint, rock solid package ecosystem.`},{id:`alpine-320`,name:`Alpine Linux 3.20.3`,family:`linux`,badge:`Micro Hypervisor`,edition:`Standard Edition`,size_formatted:`209 MB`,arch:`x86_64`,kernel:`Linux 6.6 LTS`,url:`https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/x86_64/alpine-standard-3.20.3-x86_64.iso`,filename:`alpine-standard-3.20.3-x86_64.iso`,desc:`Musl libc and BusyBox based ultra-lean OS. Boots in 400ms, uses under 32MB host RAM.`},{id:`fedora-40`,name:`Fedora Server 40`,family:`linux`,badge:`Modern Enterprise`,edition:`Server Netinstall`,size_formatted:`2.5 GB`,arch:`x86_64`,kernel:`Linux 6.8`,url:`https://download.fedoraproject.org/pub/fedora/linux/releases/40/Server/x86_64/iso/Fedora-Server-dvd-x86_64-40-1.14.iso`,filename:`Fedora-Server-dvd-x86_64-40-1.14.iso`,desc:`Leading-edge Linux platform with native systemd-nspawn, Podman, and Cockpit integration.`},{id:`truenas-scale`,name:`TrueNAS SCALE 24.04.2`,family:`storage`,badge:`Scale-Out NAS`,edition:`Dragonfish`,size_formatted:`1.7 GB`,arch:`x86_64`,kernel:`Linux 6.6 LTS`,url:`https://download.sys.truenas.net/TrueNAS-SCALE-Dragonfish/24.04.2/TrueNAS-SCALE-24.04.2.iso`,filename:`TrueNAS-SCALE-24.04.2.iso`,desc:`Debian-based open hyper-converged scale-out storage, ZFS pools, and containerized apps.`},{id:`virtio-win`,name:`VirtIO Windows Guest Tools`,family:`windows`,badge:`KVM Drivers`,edition:`Stable 0.1.262`,size_formatted:`650 MB`,arch:`x86_64 / x86`,kernel:`WHQL Signed`,url:`https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso`,filename:`virtio-win-stable.iso`,desc:`Essential Red Hat signed VirtIO storage (viostor), network (NetKVM), and memory balloon drivers.`},{id:`win-server-2022`,name:`Windows Server 2022 Eval`,family:`windows`,badge:`Microsoft Eval`,edition:`Standard / Datacenter`,size_formatted:`4.7 GB`,arch:`x86_64`,kernel:`NT 10.0`,url:`https://software-download.microsoft.com/download/pr/SERVER_EVAL_x64FRE_en-us.iso`,filename:`Windows_Server_2022_Eval_x64.iso`,desc:`Official Microsoft 180-day evaluation image for Active Directory and Windows workloads.`}],le={};async function ue(e=`catalog`){let i=document.getElementById(`modal-iso-manager`);if(!i){i=document.createElement(`div`),i.id=`modal-iso-manager`,i.className=`os-window vm-iso-window`,i.style.cssText=`display: none; width: 860px; height: 620px; min-width: 600px; min-height: 440px;`;let e=Math.max(30,Math.floor((window.innerWidth-860)/2)+20),t=Math.max(40,Math.floor((window.innerHeight-620)/2)+25);i.style.left=`${e}px`,i.style.top=`${t}px`,i.innerHTML=`
      <div class="os-window-header" id="iso-win-header" style="cursor: move;">
        <div class="os-window-title" style="display: flex; align-items: center; gap: 8px;">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/><line x1="12" y1="2" x2="12" y2="5"/></svg>
          <span>ISO Storage & Official OS Catalog</span>
        </div>
        <div class="os-window-controls">
          <button class="win-btn min-btn" id="iso-win-min" title="Minimize" aria-label="Minimize"></button>
          <button class="win-btn max-btn" id="iso-win-max" title="Maximize" aria-label="Maximize"></button>
          <button class="win-btn close-btn" id="iso-modal-close" title="Close" aria-label="Close"></button>
        </div>
      </div>

      <!-- Navigation Tabs -->
      <div class="iso-modal-tabs" style="display: flex; gap: 8px; padding: 10px 18px; background: rgba(0,0,0,0.25); border-bottom: 1px solid rgba(255,255,255,0.06); flex-shrink: 0;">
        <button id="tab-btn-catalog" class="btn-pill-toggle active" style="flex: 1; padding: 8px 14px; font-weight: 700;">
          <span>🌐 Official ISO Catalog</span>
        </button>
        <button id="tab-btn-local" class="btn-pill-toggle" style="flex: 1; padding: 8px 14px; font-weight: 700;">
          <span>📁 Local Storage ISOs (/mnt/user/isos)</span>
        </button>
      </div>

      <div class="os-window-body" style="flex: 1; overflow-y: auto; padding: 18px 22px;">
        <!-- Tab 1: Official Catalog -->
        <div id="tab-content-catalog">
          <div style="font-size: 11px; color: var(--muted); margin-bottom: 14px;">
            Verified, turnkey operating system images ready for 1-click download directly to your storage pool (<code style="color: #38bdf8;">/mnt/user/isos</code>).
          </div>
          <div class="catalog-grid" id="catalog-grid-container" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px;">
            <!-- Rendered by renderCatalogCards() -->
          </div>
        </div>

        <!-- Tab 2: Local Storage ISOs & Drag-and-Drop Upload -->
        <div id="tab-content-local" style="display: none;">
          <!-- Dropzone -->
          <div id="iso-dropzone" class="iso-dropzone" style="border: 2px dashed rgba(14,165,233,0.4); border-radius: 8px; padding: 24px; text-align: center; background: rgba(14,165,233,0.03); cursor: pointer; transition: all 0.2s;">
            <div style="font-size: 28px; margin-bottom: 8px;">💿</div>
            <div style="font-weight: 700; color: #fff; font-size: 13px;">Drag & Drop ISO files here to upload</div>
            <div style="font-size: 11px; color: var(--muted); margin-top: 4px;">Destination: <code style="color: #38bdf8;">/mnt/user/isos</code> • Supports .iso, .img up to 50 GB</div>
            <input type="file" id="iso-file-input" accept=".iso,.img" style="display: none;" />
            <button id="btn-browse-iso" class="btn-pill-toggle" style="margin-top: 12px; padding: 6px 14px; font-size: 11px;">Select ISO File...</button>
          </div>

          <!-- Upload Progress Card -->
          <div id="iso-upload-progress-card" style="display: none; margin-top: 14px; padding: 12px 14px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.08); border-radius: 6px;">
            <div style="display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 6px;">
              <span id="upload-filename" style="color: #fff; font-weight: 600;">uploading.iso</span>
              <span id="upload-rate" style="color: #38bdf8;">0 MB/s</span>
            </div>
            <div style="height: 8px; border-radius: 4px; background: rgba(255,255,255,0.1); overflow: hidden;">
              <div id="upload-progress-bar" style="width: 0%; height: 100%; background: #10b981; transition: width 0.15s;"></div>
            </div>
          </div>

          <!-- Existing Local Files Table -->
          <div style="margin-top: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
              <div style="font-size: 12px; font-weight: 700; color: #fff;">Discovered Images in /mnt/user/isos</div>
              <button id="btn-refresh-local-isos" class="btn-pill-toggle" style="padding: 3px 8px; font-size: 10px;">↺ Refresh</button>
            </div>
            <div id="local-iso-list" style="display: flex; flex-direction: column; gap: 8px;"></div>
          </div>
        </div>
      </div>
    `,document.body.appendChild(i),window.DockManager&&window.DockManager.register(`vm-iso-manager`,i,`#i-vm`,`ISO Storage & Catalog`),u(i,i.querySelector(`#iso-win-header`)),i.addEventListener(`mousedown`,()=>d(i));let n=i.querySelector(`#iso-win-min`),r=i.querySelector(`#iso-win-max`),s=i.querySelector(`#iso-modal-close`);n&&(n.onclick=e=>{if(e&&(e.preventDefault(),e.stopPropagation()),i._unbindTrap){try{i._unbindTrap()}catch{}i._unbindTrap=null}i.classList.add(`window-minimized`),i.classList.remove(`open`),i.style.setProperty(`display`,`none`,`important`),window.DockManager&&window.DockManager.minimize(`vm-iso-manager`)});let l=!1,p=null;r&&(r.onclick=()=>{l?(p&&(i.style.left=p.left,i.style.top=p.top,i.style.width=p.width,i.style.height=p.height),l=!1):(p={left:i.style.left,top:i.style.top,width:i.style.width,height:i.style.height},i.style.left=`0px`,i.style.top=`36px`,i.style.width=`100vw`,i.style.height=`calc(100vh - 36px - 72px)`,l=!0)}),s&&(s.onclick=e=>{if(e&&(e.preventDefault(),e.stopPropagation()),i._unbindTrap){try{i._unbindTrap()}catch{}i._unbindTrap=null}i.classList.add(`window-minimized`),i.classList.remove(`open`),i.style.setProperty(`display`,`none`,`important`),window.DockManager&&window.DockManager.closeWindow(`vm-iso-manager`)});let m=i.querySelector(`#iso-dropzone`),h=i.querySelector(`#iso-file-input`),g=i.querySelector(`#btn-browse-iso`);g&&h&&(g.onclick=()=>h.click(),h.onchange=e=>{let t=e.target.files[0];t&&a(t)}),m&&(m.ondragover=e=>{e.preventDefault(),m.style.borderColor=`#38bdf8`,m.style.background=`rgba(14,165,233,0.1)`},m.ondragleave=()=>{m.style.borderColor=`rgba(14,165,233,0.4)`,m.style.background=`rgba(14,165,233,0.03)`},m.ondrop=e=>{e.preventDefault(),m.style.borderColor=`rgba(14,165,233,0.4)`,m.style.background=`rgba(14,165,233,0.03)`;let t=e.dataTransfer.files[0];t&&a(t)}),i.querySelector(`#btn-refresh-local-isos`)?.addEventListener(`click`,async()=>{await b(),o(),f(),c(`ISO list refreshed.`,`info`)})}function a(e){if(!e)return;let t=i.querySelector(`#iso-upload-progress-card`),n=i.querySelector(`#upload-progress-bar`),r=i.querySelector(`#upload-filename`),a=i.querySelector(`#upload-rate`);t&&(t.style.display=`block`),r&&(r.textContent=e.name),n&&(n.style.width=`0%`),a&&(a.textContent=`Starting upload...`);let s=new XMLHttpRequest,l=Date.now(),u=0;s.upload.onprogress=e=>{if(e.lengthComputable){let t=Math.round(e.loaded/e.total*100),r=Date.now(),i=(r-l)/1e3;if(i>=.25){let n=(e.loaded-u)/1048576/i;l=r,u=e.loaded,a&&(a.textContent=`${n.toFixed(1)} MB/s (${t}%)`)}n&&(n.style.width=`${t}%`)}},s.onload=async()=>{if(s.status>=200&&s.status<300)n&&(n.style.width=`100%`),a&&(a.textContent=`Upload Complete`),c(`ISO '${e.name}' uploaded successfully to /mnt/user/isos`,`success`),await b(),o(),f(),document.getElementById(`fm-refresh-btn`)?.click();else{let e=`Upload failed`;try{let t=JSON.parse(s.responseText);t&&t.detail&&(e=t.detail)}catch{}c(`Upload failed: ${e}`,`error`),a&&(a.textContent=`Error: ${e}`)}},s.onerror=()=>{c(`Network error while uploading ISO`,`error`),a&&(a.textContent=`Network Error`)},s.open(`POST`,`/api/vms/isos/upload`),s.setRequestHeader(`x-filename`,e.name),s.withCredentials=!0,s.send(e)}function o(){let e=i.querySelector(`#local-iso-list`);e&&(!_||_.length===0?e.innerHTML=`<div style="font-size: 11px; color: var(--muted); padding: 12px 0;">No local ISO images discovered in /mnt/user/isos.</div>`:(e.innerHTML=_.map(e=>`
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px;">
          <div style="display: flex; align-items: center; gap: 10px; min-width: 0; flex: 1;">
            <span style="font-size: 18px;">💿</span>
            <div style="min-width: 0; flex: 1;">
              <div style="font-size: 12.5px; font-weight: 700; color: #fff; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">${r(e.name)}</div>
              <div style="font-size: 10.5px; color: var(--muted); font-family: monospace;">${r(e.path)}</div>
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 8px; margin-left: 12px; flex-shrink: 0;">
            <span style="font-size: 11px; font-weight: 600; color: #94a3b8;">${e.size_formatted}</span>
            <button class="btn-pill-toggle btn-boot-iso" data-path="${r(e.path)}" style="padding: 4px 10px; font-size: 11px; font-weight: 700; background: rgba(14,165,233,0.18); color: #38bdf8; border-color: rgba(14,165,233,0.35);">▶ Boot VM</button>
            <button class="btn-pill-toggle btn-delete-iso" data-path="${r(e.path)}" data-name="${r(e.name)}" style="padding: 4px 8px; font-size: 11px; color: var(--crit, #ef4444); border-color: rgba(239,68,68,0.3);" title="Delete ISO from storage">🗑</button>
          </div>
        </div>
      `).join(``),e.querySelectorAll(`.btn-boot-iso`).forEach(e=>{e.onclick=()=>{let t=e.dataset.path;window.DockManager?window.DockManager.minimize(`vm-iso-manager`):i.style.display=`none`,N();let n=document.getElementById(`vm-create-iso`);n&&(n.value=t)}}),e.querySelectorAll(`.btn-delete-iso`).forEach(e=>{e.onclick=()=>{let n=e.dataset.path,r=e.dataset.name;l(p(`vms.delete_iso_title`,`Delete ISO Image`),`Are you sure you want to delete '${r}' from storage? This cannot be undone.`,async()=>{try{await t.delete(`/api/vms/isos?path=${encodeURIComponent(n)}`),c(`ISO '${r}' deleted successfully.`,`info`),await b(),o(),f(),document.getElementById(`fm-refresh-btn`)?.click()}catch(e){c(`Failed to delete ISO: ${e.message}`,`error`)}})}})))}function s(e,n){le[e]&&clearInterval(le[e]),le[e]=setInterval(async()=>{try{let r=(await t.get(`/api/vms/catalog/tasks`)||[]).find(t=>t.catalog_id===e||t.task_id===n);if(!r)return;let a=i.querySelector(`#prog-wrap-${e}`),s=i.querySelector(`#prog-bar-${e}`),l=i.querySelector(`#prog-pct-${e}`),u=i.querySelector(`#prog-stat-${e}`),d=i.querySelector(`.btn-dl-catalog[data-id="${e}"]`);a&&(a.style.display=`block`),s&&(s.style.width=`${r.progress_pct||0}%`),l&&(l.textContent=`${r.progress_pct||0}%`),r.status===`downloading`?(u&&(u.textContent=`Downloading... ${r.speed_mb_s||0} MB/s (${r.progress_pct||0}%)`,u.style.color=`#38bdf8`),d&&(d.disabled=!0,d.textContent=`⏳ Downloading...`)):r.status===`completed`?(clearInterval(le[e]),delete le[e],s&&(s.style.width=`100%`),l&&(l.textContent=`100%`),u&&(u.textContent=`Downloaded to /mnt/user/isos`,u.style.color=`#34d399`),d&&(d.disabled=!1,d.textContent=`✓ Ready`,d.style.background=`rgba(16,185,129,0.2)`,d.style.borderColor=`#34d399`,d.style.color=`#34d399`),c(`Downloaded '${r.name||e}' to /mnt/user/isos`,`success`),await b(),f(),o(),document.getElementById(`fm-refresh-btn`)?.click()):(r.status===`failed`||r.status===`checksum_mismatch`)&&(clearInterval(le[e]),delete le[e],u&&(u.textContent=`Failed: ${r.error||`Verification error`}`,u.style.color=`#ef4444`),d&&(d.disabled=!1,d.textContent=`⬇ Retry`,d.style.opacity=`1`),c(`Download failed: ${r.error||`Error`}`,`error`))}catch{}},800)}function f(e){let n=i.querySelector(`#catalog-grid-container`);n&&(n.innerHTML=(e||ce).map(e=>{let t=(_||[]).some(t=>t.name.toLowerCase()===e.filename.toLowerCase()||t.path&&t.path.toLowerCase().endsWith(e.filename.toLowerCase()));return`
        <div class="catalog-card glassmorphic-card" style="padding: 14px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.08); background: rgba(18,26,38,0.6);">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6px;">
            <div>
              <span style="font-size: 9px; font-weight: 800; padding: 2px 6px; border-radius: 4px; background: rgba(14,165,233,0.15); color: #38bdf8;">${e.badge}</span>
              ${t?`<span style="font-size: 9px; font-weight: 800; padding: 2px 6px; border-radius: 4px; background: rgba(16,185,129,0.2); color: #34d399; margin-left: 6px;">✓ In Storage</span>`:``}
              <div style="font-weight: 700; color: #fff; font-size: 13px; margin-top: 4px;">${r(e.name)}</div>
            </div>
            <span style="font-size: 11px; font-weight: 700; color: #94a3b8;">${e.size_formatted}</span>
          </div>
          <div style="font-size: 10px; color: var(--muted); margin: 6px 0 12px 0; line-height: 1.4;">${r(e.desc||e.description||``)}</div>
          
          <!-- Download Progress Bar (Hidden by default or shown if in-flight) -->
          <div id="prog-wrap-${e.id}" style="${t?`display: block;`:`display: none;`} margin-bottom: 10px;">
            <div style="display: flex; justify-content: space-between; font-size: 10px; margin-bottom: 4px;">
              <span id="prog-stat-${e.id}" style="color: ${t?`#34d399`:`#38bdf8`};">${t?`Downloaded to /mnt/user/isos`:`Ready`}</span>
              <span id="prog-pct-${e.id}" style="color: #fff; font-weight: 700;">${t?`100%`:`0%`}</span>
            </div>
            <div style="height: 6px; border-radius: 3px; background: rgba(255,255,255,0.1); overflow: hidden;">
              <div id="prog-bar-${e.id}" style="width: ${t?`100%`:`0%`}; height: 100%; background: ${t?`#10b981`:`#0ea5e9`}; transition: width 0.2s;"></div>
            </div>
          </div>

          <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px;">
            <span style="font-size: 10px; color: var(--muted); font-family: monospace;">${e.arch||e.architecture||`x86_64`} • ${e.kernel||`Linux`}</span>
            <div style="display: flex; gap: 6px;">
              ${t?`
                <button class="btn-pill-toggle btn-boot-catalog-iso" data-filename="${e.filename}" style="padding: 5px 12px; font-size: 11px; font-weight: 700; background: rgba(14,165,233,0.18); color: #38bdf8; border-color: rgba(14,165,233,0.35);">
                  ▶ Boot VM
                </button>
                <button class="btn-save-preset btn-dl-catalog" data-id="${e.id}" disabled style="padding: 5px 10px; font-size: 11px; font-weight: 700; background: rgba(16,185,129,0.2); color: #34d399; border-color: #34d399;">
                  ✓ Ready
                </button>
              `:`
                <button class="btn-save-preset btn-dl-catalog" data-id="${e.id}" style="padding: 5px 12px; font-size: 11px; font-weight: 700; background: var(--accent-cyan, #0ea5e9); color: #fff;">
                  <span>⬇ Download</span>
                </button>
              `}
            </div>
          </div>
        </div>
      `}).join(``),n.querySelectorAll(`.btn-dl-catalog:not(:disabled)`).forEach(e=>{e.onclick=async()=>{let n=e.dataset.id;e.disabled=!0,e.textContent=`⏳ Connecting...`;let r=i.querySelector(`#prog-wrap-${n}`),a=i.querySelector(`#prog-stat-${n}`);r&&(r.style.display=`block`),a&&(a.textContent=`Contacting download mirror...`,a.style.color=`#38bdf8`);try{let e=await t.post(`/api/vms/catalog/${n}/download`);if(e&&e.status===`already_present`){c(`ISO already exists in /mnt/user/isos`,`info`),await b(),f(),o();return}s(n,e.task_id)}catch(t){c(`Failed to initiate download: ${t.message}`,`error`),a&&(a.textContent=`Error: ${t.message}`,a.style.color=`#ef4444`),e.disabled=!1,e.textContent=`⬇ Retry`}}}),n.querySelectorAll(`.btn-boot-catalog-iso`).forEach(e=>{e.onclick=()=>{let t=e.dataset.filename,n=(_||[]).find(e=>e.name.toLowerCase()===t.toLowerCase()),r=n?n.path:`/mnt/user/isos/${t}`;window.DockManager?window.DockManager.minimize(`vm-iso-manager`):i.style.display=`none`,N();let a=document.getElementById(`vm-create-iso`);a&&(a.value=r)}}))}let m=i.querySelector(`#tab-btn-catalog`),h=i.querySelector(`#tab-btn-local`),g=i.querySelector(`#tab-content-catalog`),v=i.querySelector(`#tab-content-local`);function y(e){e===`local`?(h?.classList.add(`active`),m?.classList.remove(`active`),v&&(v.style.display=`block`),g&&(g.style.display=`none`)):(m?.classList.add(`active`),h?.classList.remove(`active`),g&&(g.style.display=`block`),v&&(v.style.display=`none`))}if(m&&(m.onclick=()=>y(`catalog`)),h&&(h.onclick=()=>y(`local`)),y(e),window.DockManager?window.DockManager.restore(`vm-iso-manager`):i.style.display=`flex`,d(i),i._unbindTrap){try{i._unbindTrap()}catch{}i._unbindTrap=null}i._unbindTrap=n(i,()=>{let e=i.querySelector(`#iso-modal-close`);e?e.click():(i.classList.add(`window-minimized`),i.classList.remove(`open`),i.style.setProperty(`display`,`none`,`important`))}),o(),f();try{let[e,n]=await Promise.all([t.get(`/api/vms/catalog`).catch(()=>null),t.get(`/api/vms/catalog/tasks`).catch(()=>null)]);e&&e.length>0&&f(e),n&&n.length>0&&n.forEach(e=>{e.status===`downloading`&&s(e.catalog_id,e.task_id)})}catch{}}async function de(e,i=null){let a=document.getElementById(`modal-vm-snapshots`);a?a.className=`smart-modal-backdrop`:(a=document.createElement(`div`),a.id=`modal-vm-snapshots`,a.className=`smart-modal-backdrop`,document.body.appendChild(a));let o=i||h.find(t=>t.id===e)||{id:e,name:`Virtual Machine`,state:`stopped`};a.innerHTML=`
    <div class="smart-modal-window vm-modal-window" style="max-width: 660px; width: 92%; max-height: 85vh; display: flex; flex-direction: column; overflow: hidden;">
      <div class="smart-modal-header" style="cursor: move; user-select: none; display: flex; justify-content: space-between; align-items: center;">
        <div class="smart-modal-title" style="display: flex; align-items: center; gap: 8px;">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--accent, #38bdf8);"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
          <span>${p(`vm.snapshots`,`Snapshots & Rollback`)}: ${r(o.name)}</span>
        </div>
        <div class="os-window-controls" style="display: flex; gap: 6px; align-items: center;">
          <button class="win-btn close-btn" id="vm-snap-modal-close" title="Close" aria-label="Close"></button>
        </div>
      </div>

      <!-- Navigation Tabs -->
      <div style="display: flex; gap: 8px; border-bottom: 1px solid rgba(255,255,255,0.08); padding: 8px 18px; background: rgba(0,0,0,0.15);">
        <button type="button" id="tab-btn-snaps" class="btn-pill-toggle active" style="font-size: 11px; padding: 5px 12px; font-weight: 700; cursor: pointer; display: inline-flex; align-items: center; gap: 6px;">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
          <span>QCOW2 Checkpoints</span>
        </button>
        <button type="button" id="tab-btn-backups" class="btn-pill-toggle" style="font-size: 11px; padding: 5px 12px; font-weight: 700; cursor: pointer; display: inline-flex; align-items: center; gap: 6px;">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          <span>Hyper-Backups (.tar.gz)</span>
        </button>
      </div>

      <div class="smart-modal-body" style="flex: 1; overflow-y: auto; padding: 18px 22px; display: flex; flex-direction: column; gap: 14px;">
        <!-- SNAPSHOTS PANE -->
        <div id="vm-pane-snapshots" style="display: flex; flex-direction: column; gap: 14px;">
          <div style="display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap;">
            <div>
              <div style="font-size: 12px; font-weight: 700; color: #fff;">QCOW2 Checkpoints & State Snapshots</div>
              <div style="font-size: 10px; color: var(--muted);">Live memory + disk snapshots while running; disk snapshots while offline.</div>
            </div>
            <button type="button" id="btn-take-snapshot" class="btn-pill-toggle" style="background: rgba(14,165,233,0.15); border: 1px solid rgba(14,165,233,0.35); color: #38bdf8; font-weight: 700; font-size: 11px; padding: 5px 12px; border-radius: 6px; cursor: pointer; display: inline-flex; align-items: center; gap: 5px;">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              <span>${p(`vm.take_snapshot`,`+ Take Snapshot`)}</span>
            </button>
          </div>

          <!-- Create Snapshot Form -->
          <div id="vm-snap-create-form" style="display: none; background: rgba(0,0,0,0.3); border: 1px solid rgba(14,165,233,0.3); border-radius: 8px; padding: 12px; flex-direction: column; gap: 10px;">
            <div style="font-size: 11px; font-weight: 700; color: #38bdf8;">Create New Checkpoint Snapshot</div>
            <div style="display: flex; gap: 8px; flex-wrap: wrap;">
              <input type="text" id="vm-snap-name-input" placeholder="${p(`vm.snapshot_name`,`Snapshot Name`)}" style="flex: 1; min-width: 160px; padding: 6px 10px; border-radius: 4px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.15); color: #fff; font-size: 11px;" />
              <input type="text" id="vm-snap-desc-input" placeholder="${p(`vm.snapshot_desc`,`Description (optional)`)}" style="flex: 2; min-width: 200px; padding: 6px 10px; border-radius: 4px; background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.15); color: #fff; font-size: 11px;" />
            </div>
            <div style="display: flex; justify-content: flex-end; gap: 8px;">
              <button type="button" id="btn-cancel-take-snapshot" class="btn-pill-toggle" style="font-size: 11px; padding: 4px 10px;">Cancel</button>
              <button type="button" id="btn-submit-take-snapshot" class="btn-pill-toggle" style="background: #0284c7; color: #fff; font-weight: 700; font-size: 11px; padding: 4px 14px; cursor: pointer;">Save Snapshot</button>
            </div>
          </div>

          <div id="vm-snapshots-container" style="background: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; overflow: hidden; min-height: 120px;">
            <div style="color: var(--muted); text-align: center; padding: 28px; font-size: 12px;">Loading snapshots...</div>
          </div>
        </div>

        <!-- HYPER-BACKUPS PANE -->
        <div id="vm-pane-backups" style="display: none; flex-direction: column; gap: 14px;">
          <div style="display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap;">
            <div>
              <div style="font-size: 12px; font-weight: 700; color: #fff;">Complete VM Hyper-Backups</div>
              <div style="font-size: 10px; color: var(--muted);">Self-contained archives (.tar.gz) containing complete hardware specs and virtual disk images.</div>
            </div>
            <button type="button" id="btn-create-hyper-backup" class="btn-pill-toggle" style="background: rgba(16,185,129,0.15); border: 1px solid rgba(16,185,129,0.35); color: #34d399; font-weight: 700; font-size: 11px; padding: 5px 12px; border-radius: 6px; cursor: pointer; display: inline-flex; align-items: center; gap: 5px;">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              <span>+ Create Hyper-Backup</span>
            </button>
          </div>

          <div id="vm-backups-container" style="background: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; overflow: hidden; min-height: 120px;">
            <div style="color: var(--muted); text-align: center; padding: 28px; font-size: 12px;">Loading hyper-backups...</div>
          </div>
        </div>
      </div>
    </div>
  `,a.classList.remove(`window-minimized`),a.classList.add(`open`),a.style.removeProperty(`display`),a.style.setProperty(`display`,`flex`,`important`),a.style.zIndex=`9600`;let s=a.querySelector(`.smart-modal-window`);s&&(s.style.zIndex=`9610`,u(s,a.querySelector(`.smart-modal-header`)));let d=()=>{if(a.classList.remove(`open`),a.classList.add(`window-minimized`),a.style.setProperty(`display`,`none`,`important`),a._unbindTrap){try{a._unbindTrap()}catch{}a._unbindTrap=null}},f=a.querySelector(`#vm-snap-modal-close`);if(f&&(f.onclick=d),a.onclick=e=>{e.target===a&&d()},a._unbindTrap){try{a._unbindTrap()}catch{}a._unbindTrap=null}a._unbindTrap=n(a,d);let m=a.querySelector(`#tab-btn-snaps`),g=a.querySelector(`#tab-btn-backups`),_=a.querySelector(`#vm-pane-snapshots`),v=a.querySelector(`#vm-pane-backups`);m&&g&&(m.onclick=()=>{m.classList.add(`active`),g.classList.remove(`active`),_.style.display=`flex`,v.style.display=`none`,D()},g.onclick=()=>{g.classList.add(`active`),m.classList.remove(`active`),v.style.display=`flex`,_.style.display=`none`,O()});let y=a.querySelector(`#btn-take-snapshot`),x=a.querySelector(`#vm-snap-create-form`),S=a.querySelector(`#vm-snap-name-input`),C=a.querySelector(`#vm-snap-desc-input`),w=a.querySelector(`#btn-cancel-take-snapshot`),T=a.querySelector(`#btn-submit-take-snapshot`),E=()=>`snap-${new Date().toISOString().slice(0,10).replace(/-/g,``)}-${new Date().toTimeString().slice(0,8).replace(/:/g,``)}`;y&&x&&(y.onclick=()=>{x.style.display=x.style.display===`none`?`flex`:`none`,x.style.display===`flex`&&S&&(S.value=E(),S.focus())}),w&&x&&(w.onclick=()=>{x.style.display=`none`});async function D(){let n=a.querySelector(`#vm-snapshots-container`);if(n)try{let i=(await t.get(`/api/vms/${e}/snapshots`))?.snapshots||[];if(i.length===0){n.innerHTML=`
          <div style="color: var(--muted); text-align: center; padding: 32px 20px; font-size: 12px; display: flex; flex-direction: column; align-items: center; gap: 8px;">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity: 0.5;"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
            <span>${p(`vm.no_snapshots`,`No snapshots recorded yet. Create a checkpoint before performing major updates.`)}</span>
          </div>
        `;return}n.innerHTML=`
        <table style="width: 100%; border-collapse: collapse; font-size: 11px; text-align: left;">
          <thead>
            <tr style="border-bottom: 1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.02); color: var(--muted);">
              <th style="padding: 8px 12px;">Tag / Name</th>
              <th style="padding: 8px 12px;">Timestamp</th>
              <th style="padding: 8px 12px;">Size</th>
              <th style="padding: 8px 12px;">Mode</th>
              <th style="padding: 8px 12px; text-align: right;">Actions</th>
            </tr>
          </thead>
          <tbody>
            ${i.map(e=>`
              <tr style="border-bottom: 1px solid rgba(255,255,255,0.04);">
                <td style="padding: 8px 12px; font-weight: 700; color: #fff;">
                  <div>${r(e.name)}</div>
                  ${e.description?`<div style="font-size: 9.5px; color: var(--muted); font-weight: normal;">${r(e.description)}</div>`:``}
                </td>
                <td style="padding: 8px 12px; color: var(--muted); font-family: var(--font-mono, monospace);">${r(e.date||e.created_at||`—`)}</td>
                <td style="padding: 8px 12px; color: var(--muted);">${r(e.size_formatted||e.vm_size||`—`)}</td>
                <td style="padding: 8px 12px;">
                  <span style="font-size: 9px; padding: 2px 6px; border-radius: 4px; background: rgba(14,165,233,0.15); color: #38bdf8;">
                    ${e.is_live?`Live Memory + Disk`:`QCOW2 Disk`}
                  </span>
                </td>
                <td style="padding: 8px 12px; text-align: right;">
                  <div style="display: flex; gap: 6px; justify-content: flex-end;">
                    <button class="btn-pill-toggle btn-snap-revert" data-name="${r(e.name)}" style="padding: 4px 10px; font-size: 10px; color: #38bdf8; border-color: rgba(14,165,233,0.3); cursor: pointer; display: inline-flex; align-items: center; gap: 4px;">
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="11 17 6 12 11 7"/><polyline points="18 17 13 12 18 7"/></svg>
                      <span>${p(`vm.revert_snapshot`,`Revert`)}</span>
                    </button>
                    <button class="btn-pill-toggle btn-snap-del" data-name="${r(e.name)}" style="padding: 4px 10px; font-size: 10px; color: var(--crit, #ff6b6b); border-color: rgba(255,107,107,0.3); cursor: pointer; display: inline-flex; align-items: center; gap: 4px;">
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                      <span>${p(`vm.delete_snapshot`,`Delete`)}</span>
                    </button>
                  </div>
                </td>
              </tr>
            `).join(``)}
          </tbody>
        </table>
      `,n.querySelectorAll(`.btn-snap-revert`).forEach(n=>{n.onclick=()=>{let r=n.dataset.name;l(`Revert VM '${o.name}' to checkpoint '${r}'? Runtime modifications will be rolled back.`,async()=>{try{await t.post(`/api/vms/${e}/snapshots/${encodeURIComponent(r)}/revert`),c(`Rolled back VM '${o.name}' to snapshot '${r}'.`,`success`),D(),b()}catch(e){c(`Revert failed: ${e.message||e.detail}`,`error`)}})}}),n.querySelectorAll(`.btn-snap-del`).forEach(n=>{n.onclick=()=>{let r=n.dataset.name;l(`Delete snapshot '${r}'? This action cannot be undone.`,async()=>{try{await t.delete(`/api/vms/${e}/snapshots/${encodeURIComponent(r)}`),c(`Deleted snapshot '${r}'.`,`success`),D()}catch(e){c(`Delete failed: ${e.message||e.detail}`,`error`)}})}})}catch(e){n.innerHTML=`<div style="color: var(--crit); text-align: center; padding: 24px; font-size: 11px;">Failed to load snapshots: ${r(e.message||e.detail)}</div>`}}async function O(){let n=a.querySelector(`#vm-backups-container`);if(n)try{let i=(await t.get(`/api/vms/${e}/backups`))?.backups||[];if(i.length===0){n.innerHTML=`
          <div style="color: var(--muted); text-align: center; padding: 32px 20px; font-size: 12px; display: flex; flex-direction: column; align-items: center; gap: 8px;">
            <span style="font-size: 24px; opacity: 0.6;">💾</span>
            <span>No hyper-backups created yet. Click "+ Create Hyper-Backup" above to generate a standalone archive.</span>
          </div>
        `;return}n.innerHTML=`
        <table style="width: 100%; border-collapse: collapse; font-size: 11px; text-align: left;">
          <thead>
            <tr style="border-bottom: 1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.02); color: var(--muted);">
              <th style="padding: 8px 12px;">Backup ID / File</th>
              <th style="padding: 8px 12px;">Created</th>
              <th style="padding: 8px 12px;">Size</th>
              <th style="padding: 8px 12px; text-align: right;">Actions</th>
            </tr>
          </thead>
          <tbody>
            ${i.map(e=>`
              <tr style="border-bottom: 1px solid rgba(255,255,255,0.04);">
                <td style="padding: 8px 12px; font-weight: 700; color: #fff;">
                  <div>${r(e.filename||e.id)}</div>
                  <div style="font-size: 9.5px; color: var(--muted); font-family: var(--font-mono, monospace);">${r(e.id)}</div>
                </td>
                <td style="padding: 8px 12px; color: var(--muted); font-family: var(--font-mono, monospace);">${r(e.created_at_iso||`—`)}</td>
                <td style="padding: 8px 12px; color: var(--muted);">${r(e.size_formatted||`—`)}</td>
                <td style="padding: 8px 12px; text-align: right;">
                  <div style="display: flex; gap: 6px; justify-content: flex-end;">
                    <button class="btn-pill-toggle btn-bk-restore" data-id="${r(e.id)}" style="padding: 4px 10px; font-size: 10px; color: #34d399; border-color: rgba(16,185,129,0.3); cursor: pointer; display: inline-flex; align-items: center; gap: 4px;">
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/></svg>
                      <span>Restore</span>
                    </button>
                    <button class="btn-pill-toggle btn-bk-del" data-id="${r(e.id)}" style="padding: 4px 10px; font-size: 10px; color: var(--crit, #ff6b6b); border-color: rgba(255,107,107,0.3); cursor: pointer; display: inline-flex; align-items: center; gap: 4px;">
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                      <span>Delete</span>
                    </button>
                  </div>
                </td>
              </tr>
            `).join(``)}
          </tbody>
        </table>
      `,n.querySelectorAll(`.btn-bk-restore`).forEach(e=>{e.onclick=()=>{let n=e.dataset.id;l(`Restore VM '${o.name}' from hyper-backup archive '${n}'? Existing virtual disks and settings will be restored.`,async()=>{try{await t.post(`/api/vms/backups/${encodeURIComponent(n)}/restore`),c(`Restored VM '${o.name}' from backup '${n}'.`,`success`),O(),b()}catch(e){c(`Restore failed: ${e.message||e.detail}`,`error`)}})}}),n.querySelectorAll(`.btn-bk-del`).forEach(e=>{e.onclick=()=>{let n=e.dataset.id;l(`Delete hyper-backup archive '${n}'? This action cannot be undone.`,async()=>{try{await t.delete(`/api/vms/backups/${encodeURIComponent(n)}`),c(`Deleted backup '${n}'.`,`success`),O()}catch(e){c(`Delete failed: ${e.message||e.detail}`,`error`)}})}})}catch(e){n.innerHTML=`<div style="color: var(--crit); text-align: center; padding: 24px; font-size: 11px;">Failed to load hyper-backups: ${r(e.message||e.detail)}</div>`}}let k=a.querySelector(`#btn-create-hyper-backup`);k&&(k.onclick=async()=>{k.disabled=!0,k.textContent=`Archiving...`;try{await t.post(`/api/vms/${e}/backup`,{reason:`on-demand`}),c(`Hyper-backup created for VM '${o.name}'.`,`success`),O()}catch(e){c(`Failed creating hyper-backup: ${e.message||e.detail}`,`error`)}finally{k.disabled=!1,k.textContent=`+ Create Hyper-Backup`}}),T&&(T.onclick=async()=>{let n=(S?.value||``).trim(),r=(C?.value||``).trim();if(!n){c(`Please specify a snapshot name`,`warning`);return}T.disabled=!0,T.textContent=`Saving...`;try{await t.post(`/api/vms/${e}/snapshots`,{name:n,description:r}),c(`Snapshot '${n}' created successfully.`,`success`),x&&(x.style.display=`none`),C&&(C.value=``),D()}catch(e){c(`Failed to create snapshot: ${e.message||e.detail}`,`error`)}finally{T.disabled=!1,T.textContent=`Save Snapshot`}}),D()}typeof window<`u`&&(window.openVmConnectModal=j,window.openVmEditModal=A,window.openVmSnapshotsModal=de);export{N as C,U as D,Q as E,F as O,oe as S,de as T,ue as _,q as a,j as b,ne as c,X as d,P as f,b as g,y as h,J as i,Y as k,G as l,re as m,L as n,z as o,K as p,R as r,Z as s,ce as t,B as u,M as v,A as w,ae as x,k as y};