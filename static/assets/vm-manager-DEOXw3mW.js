import{B as e,C as t,E as n,N as r,O as i,R as a,T as o,a as s,d as c,n as l,w as u}from"./dock-CyYRv-dU.js";var d=null,f=[],p=null,m=[],h=[`br0`];function g(){if(window._vmManagerInitialized)return;window._vmManagerInitialized=!0;let t=document.getElementById(`vm-desktop-icon`),n=t=>{if(t&&t.type===`touchend`&&t.preventDefault(),window.DockManager){if(!window.DockManager.windows.vm){let e=document.getElementById(`vm-manager-window`);e&&window.DockManager.register(`vm`,e,`#i-vm`,r(`dock.vm_manager`,`Virtual Machines`))}window.DockManager.restore(`vm`)}e.emit(`window:open`,{id:`vm-manager-window`}),_()};if(t&&(t.addEventListener(`click`,n),t.addEventListener(`touchend`,n),t.addEventListener(`dblclick`,n),t.addEventListener(`keydown`,e=>{(e.key===`Enter`||e.key===` `)&&(e.preventDefault(),n())})),window.openVmManager=n,!document.getElementById(`vm-manager-window`)){let e=`
      <div id="vm-manager-window" class="os-window vm-manager-window" style="display: none; width: 920px; height: 600px; min-width: 640px; min-height: 420px;">
        <div class="os-window-header">
          <div class="os-window-title">
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
            <span data-i18n="dock.vm_manager">${r(`dock.vm_manager`,`Virtual Machines`)}</span>
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
              <button id="btn-vm-refresh" class="btn-pill-toggle" title="${r(`vm.refresh`,`Refresh`)}" style="display: inline-flex; align-items: center; gap: 6px;">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
                <span data-i18n="vm.refresh">${r(`vm.refresh`,`Refresh`)}</span>
              </button>
              <button id="btn-vm-isos" class="btn-pill-toggle" title="ISO Library & Official Catalog" style="display: inline-flex; align-items: center; gap: 6px;">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/><line x1="12" y1="2" x2="12" y2="5"/></svg>
                <span>ISO Library</span>
              </button>
              <button id="btn-vm-create" class="btn-save-preset" style="background: var(--accent-cyan, #0ea5e9); border-color: rgba(14, 165, 233, 0.4); color: #fff; font-weight: 700;">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                <span data-i18n="vm.create_btn">${i(r(`vm.create_btn`,`Create Virtual Machine`))}</span>
              </button>
            </div>
          </div>

          <div class="vm-telemetry-budget-grid" style="display: grid; grid-template-columns: 1.5fr 1fr; gap: 14px;">
            <!-- Memory Budget Card -->
            <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.05); border-radius: 8px; padding: 10px 14px;">
              <div style="display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 6px;">
                <span style="color: var(--muted); font-weight: 600;" data-i18n="vm.host_reserve">${r(`vm.host_reserve`,`Host Memory Reserve`)} (10% Dynamic)</span>
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
            <div data-i18n="vm.no_vms" style="font-weight: 600; color: #94a3b8; margin-bottom: 14px;">${r(`vm.no_vms`,`No virtual machines configured yet.`)}</div>
            <button id="btn-vm-empty-create" class="btn-save-preset" style="background: var(--accent-cyan, #0ea5e9); border-color: rgba(14, 165, 233, 0.4); color: #fff; margin: 0 auto;">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              <span data-i18n="vm.create_btn">${i(r(`vm.create_btn`,`Create Virtual Machine`))}</span>
            </button>
          </div>
          <div id="vm-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px;"></div>
        </div>
      </div>
    `;document.body.insertAdjacentHTML(`beforeend`,e)}d=document.getElementById(`vm-manager-window`);let a=document.getElementById(`vm-min`),o=document.getElementById(`vm-max`),c=document.getElementById(`vm-close`);a&&(a.onclick=e=>{e&&(e.preventDefault(),e.stopPropagation()),d&&(d.classList.add(`window-minimized`),d.classList.remove(`open`),d.style.setProperty(`display`,`none`,`important`)),window.DockManager&&window.DockManager.minimize(`vm`)}),c&&(c.onclick=e=>{e&&(e.preventDefault(),e.stopPropagation()),d&&(d.classList.add(`window-minimized`),d.classList.remove(`open`),d.style.setProperty(`display`,`none`,`important`)),window.DockManager&&window.DockManager.closeWindow(`vm`)});let u=!1,f=null;o&&(o.onclick=()=>{u?(f&&(d.style.left=f.left,d.style.top=f.top,d.style.width=f.width,d.style.height=f.height),u=!1):(f={left:d.style.left,top:d.style.top,width:d.style.width,height:d.style.height},d.style.left=`0px`,d.style.top=`36px`,d.style.width=`100vw`,d.style.height=`calc(100vh - 36px - 72px)`,u=!0)});let p=document.getElementById(`btn-vm-create`);p&&(p.onclick=()=>w());let m=document.getElementById(`btn-vm-isos`);m&&(m.onclick=()=>X(`catalog`));let h=document.getElementById(`btn-vm-empty-create`);h&&(h.onclick=()=>w());let g=document.getElementById(`btn-vm-refresh`);g&&(g.onclick=()=>_()),d&&(s(d,d.querySelector(`.os-window-header`)),d.addEventListener(`mousedown`,()=>l(d)))}async function _(){try{let[e,t,n,r]=await Promise.all([a.get(`/api/vms/telemetry`),a.get(`/api/vms`),a.get(`/api/vms/isos`),a.get(`/api/vms/bridges`)]);p=e,f=t||[],m=n||[],h=r||[`br0`],v(e),y(f)}catch(e){n(`Failed to load VM data: ${e.message}`,`error`)}}function v(e){if(!e)return;let t=document.getElementById(`vm-kvm-badge`);t&&e.kvm&&(t.innerHTML=`<span>⚡</span> <span>${i(e.kvm.badge||`KVM Active`)}</span> <span style="font-size: 10px; opacity: 0.8; margin-left: 2px;" title="View KVM Diagnostics & Fix">ℹ️</span>`,t.style.cursor=`pointer`,t.onclick=()=>C(e.kvm),e.kvm.state===`active`?(t.style.background=`rgba(16,185,129,0.15)`,t.style.color=`#34d399`,t.style.borderColor=`rgba(16,185,129,0.3)`):e.kvm.state===`restricted`?(t.style.background=`rgba(245,158,11,0.15)`,t.style.color=`#fbbf24`,t.style.borderColor=`rgba(245,158,11,0.3)`):(t.style.background=`rgba(239,68,68,0.15)`,t.style.color=`#f87171`,t.style.borderColor=`rgba(239,68,68,0.3)`));let n=e.memory_budget;if(n){let e=n.total_host_ram_gb||32,t=Math.min(100,Math.round(n.allocated_vm_ram_gb/e*100)),r=Math.min(100,Math.round(n.host_reserve_gb/e*100)),i=Math.max(0,100-t-r),a=document.getElementById(`vm-seg-running`),o=document.getElementById(`vm-seg-reserve`),s=document.getElementById(`vm-seg-headroom`);a&&(a.style.width=`${t}%`),o&&(o.style.width=`${r}%`),s&&(s.style.width=`${i}%`);let c=document.getElementById(`vm-headroom-text`);c&&(c.textContent=`${n.safe_headroom_gb} GB Safe Headroom (${n.allocated_vm_ram_gb} GB in use)`);let l=document.getElementById(`vm-total-ram`);l&&(l.textContent=`${n.total_host_ram_gb} GB`);let u=document.getElementById(`vm-safe-ceiling`);u&&(u.textContent=`${n.safe_max_vm_ram_gb} GB`)}let r=e.cpu_capacity;if(r){let e=document.getElementById(`vm-cpu-allocated`),t=document.getElementById(`vm-cpu-threads`),n=document.getElementById(`vm-cpu-ratio-badge`),i=document.getElementById(`vm-cpu-note`);e&&(e.textContent=r.allocated_vcpus),t&&(t.textContent=r.host_threads),n&&(n.textContent=r.badge||`${r.overcommit_ratio}x`,r.status===`nominal`?(n.style.background=`rgba(16,185,129,0.2)`,n.style.color=`#34d399`,i&&(i.textContent=`Optimal execution. Dedicated physical thread capacity per vCPU.`)):r.status===`moderate_overcommit`?(n.style.background=`rgba(245,158,11,0.2)`,n.style.color=`#fbbf24`,i&&(i.textContent=`Moderate overcommit. Bursty workloads normal; concurrent spikes may queue.`)):(n.style.background=`rgba(239,68,68,0.2)`,n.style.color=`#f87171`,i&&(i.textContent=`High thread contention risk. Advised only for idle background appliances.`)))}}function y(e){let o=document.getElementById(`vm-grid`),s=document.getElementById(`vm-empty-state`);if(o){if(!e||e.length===0){o.innerHTML=``,s&&(s.style.display=`block`);return}s&&(s.style.display=`none`),o.innerHTML=e.map(t=>{let n=t.state===`running`,a=t.state===`paused`,o=`<span style="padding: 2px 7px; border-radius: 4px; font-size: 10px; font-weight: 700; background: ${n?`rgba(16,185,129,0.15)`:a?`rgba(245,158,11,0.15)`:`rgba(255,255,255,0.06)`}; color: ${n?`#34d399`:a?`#fbbf24`:`#94a3b8`}; text-transform: uppercase;">${t.state}</span>`,s=t.vnc_port||5901+e.findIndex(e=>e.id===t.id)%10,c=Math.max(1,s-5900),l=t.ssh_port||2220+c,u=typeof window<`u`&&window.location&&window.location.hostname||`localhost`,d=t.ip_address?`ssh root@${t.ip_address}`:`ssh -p ${l} root@${u}`,f=`vnc://${u}:${s}`,p=t.qemu_pid||null,m=t.boot_order||(t.iso_path?`iso`:`disk`),h=t.cpu_usage_pct===void 0?0:t.cpu_usage_pct,g=t.ram_usage_pct===void 0?0:t.ram_usage_pct,_=(parseFloat(t.ram_gb||2)*(parseFloat(g)/100)).toFixed(1);return`
      <div class="glassmorphic-card" style="border-radius: 10px; padding: 14px; display: flex; flex-direction: column; justify-content: space-between; border: 1px solid rgba(255,255,255,0.08); background: rgba(18, 26, 38, 0.65);">
        <div>
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              ${t.os_family===`windows`?`<svg width="18" height="18" viewBox="0 0 24 24" fill="#38bdf8" style="flex-shrink: 0;"><path d="M0 3.449L9.75 2.1v9.451H0m10.949-9.602L24 0v11.4H10.949M0 12.6h9.75v9.451L0 20.699M10.949 12.6H24V24l-12.949-1.801"/></svg>`:t.os_family===`linux`?`<svg width="18" height="18" viewBox="0 0 24 24" fill="#fbbf24" style="flex-shrink: 0;"><path d="M12 2a5 5 0 0 0-5 5v3.1c-1.3.8-2 2-2 3.9 0 2.2 1.3 4 3 4.8V20a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2v-1.2c1.7-.8 3-2.6 3-4.8 0-1.9-.7-3.1-2-3.9V7a5 5 0 0 0-5-5zm-2 6a1 1 0 1 1 0-2 1 1 0 0 1 0 2zm4 0a1 1 0 1 1 0-2 1 1 0 0 1 0 2z"/></svg>`:`<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2" style="flex-shrink: 0;"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>`}
              <div>
                <div style="font-weight: 700; color: #fff; font-size: 13px;">${i(t.name)}</div>
                <div style="font-size: 10px; color: var(--muted);">${i(t.description||`Virtual Appliance`)}</div>
              </div>
            </div>
            <div style="display: flex; align-items: center; gap: 5px; flex-wrap: wrap; justify-content: flex-end;">
              ${m===`disk`?`<span class="vm-boot-order-pill disk" title="Boot order: Virtual disk first">💽 Disk</span>`:`<span class="vm-boot-order-pill iso" title="Boot order: ISO installer first">💿 ISO First</span>`}
              ${n?`<span class="qemu-process-badge active" title="QEMU KVM hypervisor process active">● QEMU ${p?`(${p})`:`Active`}</span>`:a?`<span class="qemu-process-badge paused" title="QEMU process paused">⏸ QEMU Paused</span>`:`<span class="qemu-process-badge stopped" title="QEMU process inactive">○ QEMU Stopped</span>`}
              ${o}
            </div>
          </div>

          <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; font-size: 11px; margin: 12px 0 8px; background: rgba(0,0,0,0.3); padding: 8px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.04);">
            <div><span style="color: var(--muted);">${r(`vm.compute`,`Compute`)}:</span> <strong style="color: #fff;">${t.vcpus} vCPUs</strong></div>
            <div><span style="color: var(--muted);">${r(`vm.memory`,`Memory`)}:</span> <strong style="color: #38bdf8;">${t.ram_gb} GB</strong></div>
            <div><span style="color: var(--muted);">${r(`vm.disk`,`Disk`)}:</span> <strong style="color: #fff;">${t.disk_size_gb} GB (${t.disk_format})</strong></div>
            <div><span style="color: var(--muted);">${r(`vm.bridge`,`Bridge`)}:</span> <strong style="color: #fff;">${i(t.bridge||`br0`)}</strong></div>
          </div>

          <!-- Real-time Live Resource Telemetry -->
          ${n?`
            <div class="vm-telemetry-row">
              <div class="vm-telemetry-item">
                <div class="vm-telemetry-header">
                  <span>vCPU Load</span>
                  <span class="telemetry-val">${h}%</span>
                </div>
                <div class="vm-telemetry-progress"><div class="fill-cpu" style="width: ${Math.min(100,Math.round(parseFloat(h)*4))}%;"></div></div>
              </div>
              <div class="vm-telemetry-item">
                <div class="vm-telemetry-header">
                  <span>RAM Used</span>
                  <span class="telemetry-val">${_} / ${t.ram_gb} GB</span>
                </div>
                <div class="vm-telemetry-progress"><div class="fill-ram" style="width: ${Math.min(100,Math.round(g))}%;"></div></div>
              </div>
            </div>
          `:``}

          <!-- Connection Info Bar with 1-Click Copy Buttons -->
          <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; padding: 4px 8px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; margin-bottom: 8px;">
            <div style="display: flex; align-items: center; gap: 6px; font-family: monospace; font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
              <span style="color: #f59e0b; display: inline-flex; align-items: center; gap: 3px;">
                <span>VNC :${c}</span>
                <button class="btn-copy-vnc" data-uri="${i(f)}" style="background: none; border: none; cursor: pointer; color: var(--muted); padding: 1px 3px; display: inline-flex; align-items: center;" title="Copy VNC URI (${f})">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                </button>
              </span>
              <span style="color: rgba(255,255,255,0.15);">|</span>
              <span style="color: #38bdf8; display: inline-flex; align-items: center; gap: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                <span>${i(d)}</span>
                <button class="btn-copy-ssh-cmd" data-cmd="${i(d)}" style="background: none; border: none; cursor: pointer; color: var(--muted); padding: 1px 3px; display: inline-flex; align-items: center;" title="Copy SSH Command">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                </button>
              </span>
            </div>
            <button class="btn-vm-join-toggle" data-id="${t.id}" style="background: rgba(14,165,233,0.15); border: 1px solid rgba(14,165,233,0.3); border-radius: 4px; color: #38bdf8; font-size: 10px; font-weight: 700; padding: 2px 6px; cursor: pointer; flex-shrink: 0;" title="Join VM connection options">
              Join ▾
            </button>
          </div>

          ${t.iso_path?`
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; padding: 6px 10px; background: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.3); border-radius: 4px; margin-bottom: 10px;">
              <span style="color: #fbbf24; font-weight: 600; display: flex; align-items: center; gap: 6px;">
                <span>💿</span>
                <span>ISO Attached (${i(t.iso_path.split(`/`).pop())})</span>
              </span>
              <div style="display: flex; gap: 4px;">
                <button class="btn-join-gui" data-id="${t.id}" data-name="${i(t.name)}" style="background: rgba(245,158,11,0.2); border: 1px solid rgba(245,158,11,0.4); border-radius: 4px; color: #fbbf24; font-size: 10px; font-weight: 700; padding: 2px 8px; cursor: pointer;">
                  Open Console 🖥️
                </button>
                <button class="btn-join-separate" data-id="${t.id}" data-name="${i(t.name)}" data-mode="gui" style="background: rgba(245,158,11,0.2); border: 1px solid rgba(245,158,11,0.4); border-radius: 4px; color: #fbbf24; font-size: 10px; font-weight: 700; padding: 2px 6px; cursor: pointer;" title="${r(`vm.open_separate`,`Open in Separate Window`)}">
                  ↗
                </button>
              </div>
            </div>
          `:t.ip_address?`
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; padding: 4px 8px; background: rgba(14,165,233,0.1); border: 1px solid rgba(14,165,233,0.25); border-radius: 4px; margin-bottom: 10px; position: relative;">
              <span style="color: #38bdf8; font-family: monospace; display: flex; align-items: center; gap: 5px;">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                ${i(t.ip_address)}
              </span>
              <div style="display: flex; align-items: center; gap: 4px;">
                <button class="btn-copy-ip" data-ip="${i(t.ip_address)}" style="background: none; border: none; cursor: pointer; color: var(--muted); padding: 2px 4px; display: flex; align-items: center;" title="Copy IP">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                </button>
              </div>

              <!-- Quick Connect Popover -->
              <div id="vm-join-popover-${t.id}" class="vm-join-popover" style="display: none;">
                <div style="font-size: 10px; font-weight: 800; color: var(--muted); padding-bottom: 4px; border-bottom: 1px solid rgba(255,255,255,0.06); margin-bottom: 4px;">CONNECT TO ${i(t.name).toUpperCase()}</div>
                <div class="join-popover-item btn-join-gui" data-id="${t.id}" data-name="${i(t.name)}">
                  <span>🖥️ ${r(`vm.open_gui`,`Open KVM GUI Desktop (Display :0)`)}</span>
                  <span style="font-size: 9px; color: #38bdf8;">noVNC</span>
                </div>
                <div class="join-popover-item btn-join-separate" data-id="${t.id}" data-name="${i(t.name)}" data-mode="gui">
                  <span>↗ ${r(`vm.open_separate`,`Open in Separate Window`)}</span>
                  <span style="font-size: 9px; color: #38bdf8;">Pop Out</span>
                </div>
                <div class="join-popover-item btn-join-console" data-id="${t.id}" data-name="${i(t.name)}">
                  <span>📟 ${r(`vm.open_serial`,`Open Serial Terminal (TTY)`)}</span>
                  <span style="font-size: 9px; color: #34d399;">TTY / CLI</span>
                </div>
                <div class="join-popover-item btn-join-web" data-ip="${i(t.ip_address)}">
                  <span>🌐 ${r(`vm.open_web`,`Open Web UI (HTTP)`)}</span>
                  <span style="font-size: 9px; color: #a78bfa;">http://${i(t.ip_address)}</span>
                </div>
                <div class="join-popover-item btn-join-vnc" data-id="${t.id}">
                  <span>🔗 ${r(`vm.native_vnc`,`Native VNC Client (vnc://)`)}</span>
                  <span style="font-size: 9px; color: #f59e0b;">Port ${s}</span>
                </div>
                <div class="join-popover-item btn-join-rdp" data-ip="${i(t.ip_address)}">
                  <span>🪟 ${r(`vm.rdp`,`Remote Desktop (RDP)`)}</span>
                  <span style="font-size: 9px; color: #38bdf8;">${i(t.ip_address)}:3389</span>
                </div>
                <div class="join-popover-item btn-join-ssh" data-ip="${i(t.ip_address)}">
                  <span>💻 ${r(`vm.copy_ssh`,`Copy SSH Command`)}</span>
                  <span style="font-size: 9px; font-family: monospace; color: #38bdf8;">${i(d)}</span>
                </div>
                <div class="join-popover-item btn-join-ip" data-ip="${i(t.ip_address)}">
                  <span>📋 ${r(`vm.copy_ip`,`Copy IP Address`)}</span>
                  <span style="font-size: 9px; font-family: monospace; color: #38bdf8;">${i(t.ip_address)}</span>
                </div>
                <div class="join-popover-item btn-join-details" data-id="${t.id}" style="border-top: 1px solid rgba(255,255,255,0.08); margin-top: 2px; color: #38bdf8;">
                  <span>⚡ Multi-Protocol Drawer...</span>
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                </div>
              </div>
            </div>
          `:n?`
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; padding: 6px 10px; background: rgba(14,165,233,0.08); border: 1px solid rgba(14,165,233,0.2); border-radius: 4px; margin-bottom: 10px;">
              <span style="color: #38bdf8; display: flex; align-items: center; gap: 6px;">
                <span>🖥️</span>
                <span>Console Display Active</span>
              </span>
              <div style="display: flex; gap: 4px;">
                <button class="btn-join-gui" data-id="${t.id}" data-name="${i(t.name)}" style="background: rgba(14,165,233,0.2); border: 1px solid rgba(14,165,233,0.4); border-radius: 4px; color: #38bdf8; font-size: 10px; font-weight: 700; padding: 2px 8px; cursor: pointer;">
                  Open Console 🖥️
                </button>
                <button class="btn-join-separate" data-id="${t.id}" data-name="${i(t.name)}" data-mode="gui" style="background: rgba(14,165,233,0.2); border: 1px solid rgba(14,165,233,0.4); border-radius: 4px; color: #38bdf8; font-size: 10px; font-weight: 700; padding: 2px 6px; cursor: pointer;" title="${r(`vm.open_separate`,`Open in Separate Window`)}">
                  ↗
                </button>
              </div>
            </div>
          `:``}
        </div>

        <div style="display: flex; gap: 6px; margin-top: 10px; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 10px; flex-wrap: wrap;">
          ${!n&&!a?`
            <button class="btn-vm-action btn-vm-start" data-id="${t.id}" data-act="start" style="flex: 1;" title="${r(`vm.start`,`Start`)}">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              <span>${r(`vm.start`,`Start`)}</span>
            </button>
            <button class="btn-vm-edit" data-id="${t.id}" title="Edit VM Configuration">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
              <span>Edit</span>
            </button>
            <button class="btn-vm-delete" data-id="${t.id}" data-name="${i(t.name)}" title="${r(`vm.delete`,`Delete`)}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
              <span>${r(`vm.delete`,`Delete`)}</span>
            </button>
          `:``}
          ${n?`
            <button class="btn-vm-action btn-vm-pause" data-id="${t.id}" data-act="pause" style="flex: 1;" title="${r(`vm.pause`,`Pause`)}">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
              <span>${r(`vm.pause`,`Pause`)}</span>
            </button>
            <button class="btn-vm-action btn-vm-restart" data-id="${t.id}" data-act="restart" style="flex: 1;" title="Restart VM">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
              <span>Restart</span>
            </button>
            <button class="btn-vm-action btn-vm-acpi" data-id="${t.id}" data-act="stop" style="flex: 1;" title="ACPI Shutdown (Graceful Power Off)">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg>
              <span>Shutdown</span>
            </button>
            <button class="btn-vm-action btn-vm-stop btn-vm-force-off" data-id="${t.id}" data-act="force_off" style="flex: 1;" title="Force Stop (Hard Power Cut)">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>
              <span>Force Stop</span>
            </button>
            <button class="btn-vm-gui" data-id="${t.id}" title="${r(`vm.gui`,`KVM GUI`)}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
              <span>${r(`vm.gui`,`KVM GUI`)}</span>
            </button>
            <button class="btn-vm-console" data-id="${t.id}" title="${r(`vm.console`,`Console`)}">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
              <span>${r(`vm.console`,`Console`)}</span>
            </button>
            <button class="btn-vm-edit" data-id="${t.id}" title="Edit VM Configuration">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
              <span>Edit</span>
            </button>
          `:``}
          ${a?`
            <button class="btn-vm-action btn-vm-resume" data-id="${t.id}" data-act="resume" style="flex: 1;" title="${r(`vm.resume`,`Resume`)}">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              <span>${r(`vm.resume`,`Resume`)}</span>
            </button>
            <button class="btn-vm-action btn-vm-acpi" data-id="${t.id}" data-act="stop" style="flex: 1;" title="ACPI Shutdown">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg>
              <span>Shutdown</span>
            </button>
            <button class="btn-vm-action btn-vm-stop btn-vm-force-off" data-id="${t.id}" data-act="force_off" style="flex: 1;" title="Force Stop">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>
              <span>Force Stop</span>
            </button>
            <button class="btn-vm-edit" data-id="${t.id}" title="Edit VM Configuration">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
              <span>Edit</span>
            </button>
          `:``}
          <button type="button" class="btn-vm-more-sheet" data-id="${t.id}" title="More Actions" style="display:none;">···</button>
        </div>
      </div>
    `}).join(``),o.querySelectorAll(`.btn-vm-more-sheet`).forEach(e=>{e.onclick=n=>{n.stopPropagation();let i=e.dataset.id,a=f.find(e=>e.id===i),o=a?a.name:`Virtual Machine`,s=(a?.state||`stopped`).toLowerCase(),c=s===`running`,l=s===`paused`,u=e.closest(`.vm-card`),d=[];c?d.push({icon:`🖥️`,label:r(`vm.gui`,`KVM GUI`),onClick:()=>G(i,o,`gui`)},{icon:`⌨️`,label:r(`vm.console`,`Console (Serial TTY)`),onClick:()=>G(i,o,`cli`)},{icon:`⏸️`,label:r(`vm.pause`,`Pause VM`),onClick:()=>u?.querySelector(`.btn-vm-pause`)?.click()},{icon:`🔄`,label:`Restart VM`,onClick:()=>u?.querySelector(`.btn-vm-restart`)?.click()},{icon:`⏻`,label:`ACPI Shutdown`,onClick:()=>u?.querySelector(`.btn-vm-acpi`)?.click()},{icon:`⏹️`,label:`Force Stop (Hard Power Cut)`,destructive:!0,onClick:()=>u?.querySelector(`.btn-vm-force-off`)?.click()},{icon:`✏️`,label:`Edit VM Configuration`,onClick:()=>x(i)}):l?d.push({icon:`▶️`,label:r(`vm.resume`,`Resume VM`),onClick:()=>u?.querySelector(`.btn-vm-resume`)?.click()},{icon:`⏻`,label:`ACPI Shutdown`,onClick:()=>u?.querySelector(`.btn-vm-acpi`)?.click()},{icon:`⏹️`,label:`Force Stop (Hard Power Cut)`,destructive:!0,onClick:()=>u?.querySelector(`.btn-vm-force-off`)?.click()},{icon:`✏️`,label:`Edit VM Configuration`,onClick:()=>x(i)}):d.push({icon:`▶️`,label:`Start VM`,onClick:()=>u?.querySelector(`.btn-vm-start`)?.click()},{icon:`✏️`,label:`Edit VM Configuration`,onClick:()=>x(i)},{icon:`🗑️`,label:r(`vm.delete`,`Delete VM`),destructive:!0,onClick:()=>u?.querySelector(`.btn-vm-delete`)?.click()}),t({title:o,subtitle:`${s.toUpperCase()} • ${a?.vcpus||2} vCPU • ${a?.memory_mb||2048} MB`,items:d})}}),o.querySelectorAll(`.btn-vm-action`).forEach(e=>{e.onclick=async()=>{let t=e.dataset.id,r=e.dataset.act,i=f.find(e=>e.id===t),o=i?i.name:`Virtual Machine`;try{await a.post(`/api/vms/${t}/action`,{action:r}),n(`VM action '${r}' completed`,`success`),_()}catch(e){let i=e.detail||e.message||`Unknown hypervisor error`;r===`start`||r===`restart`?b(o,i,t):n(`Action failed: ${i}`,`error`)}}}),o.querySelectorAll(`.btn-vm-edit`).forEach(e=>{e.onclick=t=>{t.stopPropagation();let n=e.dataset.id;x(n)}}),o.querySelectorAll(`.btn-copy-vnc`).forEach(e=>{e.onclick=async t=>{t.stopPropagation();let r=e.dataset.uri;await T(r)?n(`Copied VNC URI '${r}'`,`info`):n(`Failed to copy VNC URI`,`error`)}}),o.querySelectorAll(`.btn-copy-ssh-cmd`).forEach(e=>{e.onclick=async t=>{t.stopPropagation();let r=e.dataset.cmd;await T(r)?n(`Copied '${r}' to clipboard`,`info`):n(`Failed to copy SSH command`,`error`)}}),o.querySelectorAll(`.btn-vm-delete`).forEach(e=>{e.onclick=()=>{let t=e.dataset.id,i=e.dataset.name;u(r(`vm.delete`,`Delete`),`${r(`vm.delete_confirm`,`Are you sure you want to delete virtual machine`)} '${i}'?`,async()=>{try{await a.delete(`/api/vms/${t}`),n(`VM '${i}' deleted`,`success`),_()}catch(e){n(`Delete failed: ${e.message}`,`error`)}})}}),o.querySelectorAll(`.btn-copy-ip`).forEach(e=>{e.onclick=async t=>{t.stopPropagation();let r=e.dataset.ip;await T(r)?n(`Copied ${r} to clipboard`,`info`):n(`Failed to copy ${r}`,`error`)}}),o.querySelectorAll(`.btn-vm-join-toggle`).forEach(e=>{e.onclick=t=>{t.stopPropagation();let n=e.dataset.id,r=document.getElementById(`vm-join-popover-${n}`);if(r){let e=r.style.display===`none`;document.querySelectorAll(`.vm-join-popover`).forEach(e=>e.style.display=`none`),r.style.display=e?`flex`:`none`}}}),o.querySelectorAll(`.btn-join-ssh`).forEach(e=>{e.onclick=async t=>{t.stopPropagation();let r=`ssh root@${e.dataset.ip}`;await T(r)&&n(`Copied '${r}' to clipboard`,`info`),document.querySelectorAll(`.vm-join-popover`).forEach(e=>e.style.display=`none`)}}),o.querySelectorAll(`.btn-join-ip`).forEach(e=>{e.onclick=async t=>{t.stopPropagation();let r=e.dataset.ip;await T(r)&&n(`Copied ${r} to clipboard`,`info`),document.querySelectorAll(`.vm-join-popover`).forEach(e=>e.style.display=`none`)}}),o.querySelectorAll(`.btn-join-separate`).forEach(e=>{e.onclick=t=>{t.stopPropagation();let n=e.dataset.id,r=f.find(e=>e.id===n),i=r?r.name:e.dataset.name||`Virtual Machine`,a=e.dataset.mode||`gui`;document.querySelectorAll(`.vm-join-popover`).forEach(e=>e.style.display=`none`),K(n,i,a)}}),o.querySelectorAll(`.btn-vm-gui, .btn-join-gui`).forEach(e=>{e.onclick=t=>{t.stopPropagation();let n=e.dataset.id,r=f.find(e=>e.id===n),i=r?r.name:e.dataset.name||`Virtual Machine`;document.querySelectorAll(`.vm-join-popover`).forEach(e=>e.style.display=`none`),G(n,i,`gui`)}}),o.querySelectorAll(`.btn-join-console, .btn-vm-console`).forEach(e=>{e.onclick=t=>{t.stopPropagation();let n=e.dataset.id,r=f.find(e=>e.id===n),i=r?r.name:e.dataset.name||`Virtual Machine`;document.querySelectorAll(`.vm-join-popover`).forEach(e=>e.style.display=`none`),G(n,i,`cli`)}}),o.querySelectorAll(`.btn-join-web`).forEach(e=>{e.onclick=t=>{t.stopPropagation();let n=e.dataset.ip;n&&window.open(`http://${n}`,`_blank`),document.querySelectorAll(`.vm-join-popover`).forEach(e=>e.style.display=`none`)}}),o.querySelectorAll(`.btn-join-vnc`).forEach(e=>{e.onclick=async t=>{t.stopPropagation();let r=e.dataset.id,i=5900+(parseInt(r,10)||1)%10,a=`vnc://${window.location.hostname||`127.0.0.1`}:${i}`;await T(a)&&n(`Copied VNC URI '${a}' for native client`,`info`),document.querySelectorAll(`.vm-join-popover`).forEach(e=>e.style.display=`none`)}}),o.querySelectorAll(`.btn-join-rdp`).forEach(e=>{e.onclick=async t=>{t.stopPropagation();let r=`${e.dataset.ip}:3389`;await T(r)&&n(`Copied RDP Address '${r}'`,`info`),document.querySelectorAll(`.vm-join-popover`).forEach(e=>e.style.display=`none`)}}),o.querySelectorAll(`.btn-join-details`).forEach(e=>{e.onclick=t=>{t.stopPropagation();let n=e.dataset.id;document.querySelectorAll(`.vm-join-popover`).forEach(e=>e.style.display=`none`),S(n)}}),window._vmJoinDismissRegistered||(window._vmJoinDismissRegistered=!0,document.addEventListener(`click`,()=>{document.querySelectorAll(`.vm-join-popover`).forEach(e=>e.style.display=`none`)}))}}function b(e,t,n=null){let r=document.getElementById(`modal-qemu-error`);r?r.className=`smart-modal-backdrop`:(r=document.createElement(`div`),r.id=`modal-qemu-error`,r.className=`smart-modal-backdrop`,document.body.appendChild(r)),r.innerHTML=`
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
          Failed to start virtual machine <strong>${i(e)}</strong>. The hypervisor process encountered a critical error:
        </div>
        <div class="qemu-error-box" style="background: rgba(0,0,0,0.5); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 6px; padding: 12px; font-family: monospace; font-size: 11px; color: #fca5a5; line-height: 1.5; white-space: pre-wrap; word-break: break-all; max-height: 160px; overflow-y: auto;">${i(t||`Process exited prematurely with non-zero exit code.`)}</div>
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
  `,r.classList.add(`open`),r.style.display=`flex`;let a=r.querySelector(`#qemu-error-close`),o=r.querySelector(`#btn-qemu-error-dismiss`),s=r.querySelector(`#btn-qemu-error-diag`),c=r.querySelector(`#btn-qemu-error-edit`),l=()=>{r.classList.remove(`open`),r.style.display=`none`};a&&(a.onclick=l),o&&(o.onclick=l),r.onclick=e=>{e.target===r&&l()},s&&(s.onclick=()=>{l(),C()}),c&&n&&(c.onclick=()=>{l(),x(n)})}function x(e){let t=document.getElementById(`modal-vm-edit`);t?t.className=`smart-modal-backdrop`:(t=document.createElement(`div`),t.id=`modal-vm-edit`,t.className=`smart-modal-backdrop`,document.body.appendChild(t));let r=f.find(t=>t.id===e);if(!r){n(`Virtual machine '${e}' not found`,`error`);return}let o=r.state===`running`,s=p?.memory_budget||{total_host_ram_gb:32,safe_max_vm_ram_gb:28.8,safe_slider_max_gb:28,safe_headroom_gb:20.8,override_max_ram_gb:31},c=p?.cpu_capacity?.host_threads||8,l=r.boot_order||(r.iso_path?`iso`:`disk`);t.innerHTML=`
    <div class="smart-modal-window vm-modal-window" style="max-width: 580px; width: 92%; max-height: 88vh; display: flex; flex-direction: column;">
      <div class="smart-modal-header" style="cursor: move;">
        <div class="smart-modal-title">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
          <span>Edit VM Configuration: ${i(r.name)}</span>
        </div>
        <button id="vm-edit-modal-close" class="modal-close-btn" style="background: none; border: none; color: var(--muted); cursor: pointer; font-size: 16px; padding: 4px 8px; border-radius: 4px;" title="Close" aria-label="Close">✕</button>
      </div>

      <div class="smart-modal-body" style="flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 14px; padding: 18px 22px;">
        ${o?`
          <div style="background: rgba(14,165,233,0.12); border: 1px solid rgba(14,165,233,0.3); border-radius: 6px; padding: 10px 14px; font-size: 11px; color: #38bdf8; display: flex; align-items: center; gap: 8px;">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
            <span>This VM is currently <strong>running</strong>. Hardware changes (vCPUs, RAM, boot order) will take full effect on next VM restart.</span>
          </div>
        `:``}

        <!-- General Info -->
        <div>
          <label style="display: block; font-size: 11px; font-weight: 700; color: var(--muted); margin-bottom: 6px;">VM Name *</label>
          <input type="text" id="vm-edit-name" value="${i(r.name||``)}" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.12); color: #fff; font-size: 12px; box-sizing: border-box;" />
        </div>

        <div>
          <label style="display: block; font-size: 11px; font-weight: 700; color: var(--muted); margin-bottom: 6px;">Description</label>
          <input type="text" id="vm-edit-desc" value="${i(r.description||``)}" placeholder="Appliance description" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.12); color: #fff; font-size: 12px; box-sizing: border-box;" />
        </div>

        <!-- RAM Allocation & Dynamic Headroom -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 12px; font-weight: 700; color: #fff;">RAM Allocation (Dynamic Headroom)</span>
            <span id="vm-edit-ram-display" style="font-size: 12px; font-weight: 700; color: #38bdf8;">${r.ram_gb||4} GB</span>
          </div>
          <input type="range" id="vm-edit-ram-slider" min="0.5" max="${Math.max(s.safe_slider_max_gb,r.ram_gb||4)}" step="0.5" value="${r.ram_gb||4}" style="width: 100%; accent-color: var(--accent-cyan, #0ea5e9); cursor: pointer;" />
          <div style="display: flex; justify-content: space-between; font-size: 10px; color: var(--muted); margin-top: 4px;">
            <span>Min: 0.5 GB</span>
            <span id="vm-edit-slider-max-label">Safe Max: ${s.safe_slider_max_gb} GB</span>
          </div>
          <div style="margin-top: 10px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.05); display: flex; justify-content: space-between; align-items: center;">
            <label style="font-size: 11px; color: var(--muted); cursor: pointer; display: flex; align-items: center; gap: 6px;">
              <input type="checkbox" id="vm-edit-override-toggle" ${r.override_active?`checked`:``} style="accent-color: #f59e0b;" />
              <span>Advanced Override (Bypass Headroom)</span>
            </label>
            <span id="vm-edit-override-pill" style="display: ${r.override_active?`inline-block`:`none`}; font-size: 9px; padding: 2px 6px; border-radius: 4px; background: rgba(245,158,11,0.2); color: #fbbf24; border: 1px solid rgba(245,158,11,0.4);">
              ⚡ Host reserve bypassed
            </span>
          </div>
        </div>

        <!-- vCPUs Slider -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 12px; font-weight: 700; color: #fff;">vCPU Cores</span>
            <span id="vm-edit-vcpu-display" style="font-size: 12px; font-weight: 700; color: #fff;">${r.vcpus||2} vCPUs</span>
          </div>
          <input type="range" id="vm-edit-vcpu-slider" min="1" max="${Math.max(c,r.vcpus||2)}" step="1" value="${r.vcpus||2}" style="width: 100%; accent-color: var(--accent-cyan, #0ea5e9); cursor: pointer;" />
          <div style="display: flex; justify-content: space-between; font-size: 10px; color: var(--muted); margin-top: 4px;">
            <span>1 vCPU</span>
            <span>Physical Limit: ${c} Threads</span>
          </div>
          <div id="vm-edit-overcommit-warning" style="display: ${(r.vcpus||2)>c?`block`:`none`}; margin-top: 8px; font-size: 10px; padding: 6px 10px; border-radius: 4px; background: rgba(245,158,11,0.15); color: #fbbf24; border: 1px solid rgba(245,158,11,0.3);">
            ⚠️ Soft warning: Exceeds physical host threads.
          </div>
        </div>

        <!-- ISO Attach / Detach & Boot Order -->
        <div style="display: flex; flex-direction: column; gap: 10px; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <label style="font-size: 11px; font-weight: 700; color: var(--muted);">Attached ISO Image (CD-ROM)</label>
              ${r.iso_path?`<span style="font-size: 10px; color: #fbbf24;">💿 Currently Attached</span>`:``}
            </div>
            <select id="vm-edit-iso" class="tz-select" style="width: 100%; padding: 8px 10px; border-radius: 6px; background: #1e293b; border: 1px solid rgba(255,255,255,0.12); color: #fff; font-size: 12px; box-sizing: border-box;">
              <option value="">None (Detach ISO / Empty Tray)</option>
              ${m.map(e=>`<option value="${i(e.path)}" ${e.path===r.iso_path?`selected`:``}>${i(e.name)} (${e.size_formatted})</option>`).join(``)}
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
            <input type="checkbox" id="vm-edit-autostart" ${r.autostart?`checked`:``} style="accent-color: var(--accent-cyan, #0ea5e9);" />
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
  `,t.classList.add(`open`),t.style.display=`flex`;let u=t.querySelector(`#vm-edit-modal-close`),d=t.querySelector(`#vm-edit-cancel`),h=t.querySelector(`#vm-edit-submit`),g=t.querySelector(`#vm-edit-ram-slider`),v=t.querySelector(`#vm-edit-ram-display`),y=t.querySelector(`#vm-edit-vcpu-slider`),b=t.querySelector(`#vm-edit-vcpu-display`),x=t.querySelector(`#vm-edit-override-toggle`),S=t.querySelector(`#vm-edit-override-pill`),C=t.querySelector(`#vm-edit-slider-max-label`),w=t.querySelector(`#vm-edit-overcommit-warning`),T=()=>{t.classList.remove(`open`),t.style.display=`none`};u&&(u.onclick=T),d&&(d.onclick=T),t.onclick=e=>{e.target===t&&T()},g&&v&&(g.oninput=()=>{v.textContent=`${parseFloat(g.value).toFixed(1)} GB`}),x&&(x.onchange=()=>{x.checked?(g.max=s.override_max_ram_gb||31,C&&(C.textContent=`Override Max: ${g.max} GB`),S&&(S.style.display=`inline-block`)):(g.max=s.safe_slider_max_gb||28,parseFloat(g.value)>g.max&&(g.value=g.max,v.textContent=`${g.value} GB`),C&&(C.textContent=`Safe Max: ${g.max} GB`),S&&(S.style.display=`none`))}),y&&b&&(y.oninput=()=>{let e=parseInt(y.value,10);b.textContent=`${e} vCPUs`,w&&(w.style.display=e>c?`block`:`none`)});let E=t.querySelector(`#vm-edit-host-shares-list`),D=t.querySelector(`#btn-edit-add-host-share`),O=(e={})=>{let t=document.createElement(`div`);t.className=`host-share-row`,t.style.cssText=`display: flex; gap: 6px; align-items: center;`,t.innerHTML=`
      <input type="text" class="share-host-path" placeholder="/mnt/user/appdata" value="${i(e.host_path||`/mnt/user/appdata`)}" style="flex: 2; padding: 6px 8px; border-radius: 4px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
      <input type="text" class="share-mount-tag" placeholder="appdata" value="${i(e.mount_tag||`appdata`)}" style="flex: 1.2; padding: 6px 8px; border-radius: 4px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
      <select class="share-driver" style="flex: 1; padding: 6px 4px; border-radius: 4px; background: #1e293b; border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;">
        <option value="virtiofs" ${e.driver===`virtiofs`?`selected`:``}>VirtIO-FS</option>
        <option value="9p" ${e.driver===`9p`?`selected`:``}>9p</option>
      </select>
      <select class="share-mode" style="width: 60px; padding: 6px 4px; border-radius: 4px; background: #1e293b; border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;">
        <option value="rw" ${e.readonly?``:`selected`}>RW</option>
        <option value="ro" ${e.readonly?`selected`:``}>RO</option>
      </select>
      <button type="button" class="btn-remove-share" style="background: none; border: none; color: #f87171; cursor: pointer; padding: 2px 6px;">✕</button>
    `,t.querySelector(`.btn-remove-share`).onclick=()=>t.remove(),E.appendChild(t)};D&&E&&(D.onclick=()=>O(),r.host_shares&&Array.isArray(r.host_shares)&&r.host_shares.forEach(e=>O(e)));let k=t.querySelector(`#vm-edit-secondary-disks-list`),A=t.querySelector(`#btn-edit-add-secondary-disk`),j=(e={})=>{let t=(k.children.length||0)+1,n=document.createElement(`div`);n.className=`secondary-disk-row`,n.style.cssText=`display: flex; gap: 6px; align-items: center;`,n.innerHTML=`
      <input type="text" class="disk-name" placeholder="Disk Name" value="${i(e.name||`data-disk-${t}`)}" style="flex: 2; padding: 6px 8px; border-radius: 4px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
      <input type="number" class="disk-size" min="5" max="4000" placeholder="Size (GB)" value="${e.size_gb||50}" style="width: 80px; padding: 6px 8px; border-radius: 4px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
      <select class="disk-bus" style="width: 80px; padding: 6px 4px; border-radius: 4px; background: #1e293b; border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;">
        <option value="virtio" ${e.bus===`virtio`?`selected`:``}>virtio</option>
        <option value="sata" ${e.bus===`sata`?`selected`:``}>sata</option>
        <option value="nvme" ${e.bus===`nvme`?`selected`:``}>nvme</option>
      </select>
      <button type="button" class="btn-remove-disk" style="background: none; border: none; color: #f87171; cursor: pointer; padding: 2px 6px;">✕</button>
    `,n.querySelector(`.btn-remove-disk`).onclick=()=>n.remove(),k.appendChild(n)};A&&k&&(A.onclick=()=>j(),r.secondary_disks&&Array.isArray(r.secondary_disks)&&r.secondary_disks.forEach(e=>j(e))),h&&(h.onclick=async()=>{let i=t.querySelector(`#vm-edit-name`)?.value?.trim(),o=t.querySelector(`#vm-edit-desc`)?.value?.trim(),s=parseFloat(t.querySelector(`#vm-edit-ram-slider`)?.value||r.ram_gb),c=parseInt(t.querySelector(`#vm-edit-vcpu-slider`)?.value||r.vcpus,10),l=t.querySelector(`#vm-edit-iso`)?.value||null,u=t.querySelector(`input[name="vm-edit-boot-order"]:checked`)?.value||`iso`,d=t.querySelector(`#vm-edit-autostart`)?.checked??r.autostart,f=t.querySelector(`#vm-edit-override-toggle`)?.checked??!1,p=[];t.querySelectorAll(`.host-share-row`).forEach(e=>{let t=e.querySelector(`.share-host-path`)?.value?.trim(),n=e.querySelector(`.share-mount-tag`)?.value?.trim(),r=e.querySelector(`.share-driver`)?.value||`virtiofs`,i=e.querySelector(`.share-mode`)?.value===`ro`;t&&n&&p.push({host_path:t,mount_tag:n,driver:r,readonly:i})});let m=[];if(t.querySelectorAll(`.secondary-disk-row`).forEach(e=>{let t=e.querySelector(`.disk-name`)?.value?.trim(),n=parseInt(e.querySelector(`.disk-size`)?.value,10),r=e.querySelector(`.disk-bus`)?.value||`virtio`;t&&n>0&&m.push({name:t,size_gb:n,bus:r})}),!i){n(`VM Name is required`,`error`);return}let g={name:i,description:o,ram_gb:s,vcpus:c,iso_path:l,boot_order:u,autostart:d,override_limits:f,host_shares:p,secondary_disks:m};try{h.disabled=!0,h.textContent=`Saving...`;try{a.put?await a.put(`/api/vms/${e}`,g):await a.post(`/api/vms/${e}`,g)}catch(t){if(t.status===405||t.status===404)await a.post(`/api/vms/${e}`,g).catch(()=>null);else throw t}Object.assign(r,g),n(`VM '${i}' configuration updated`,`success`),T(),_()}catch(e){n(`Failed to update VM: ${e.message||`Error`}`,`error`)}finally{h&&(h.disabled=!1,h.textContent=`Save Configuration`)}})}function S(e){let t=document.getElementById(`modal-vm-connect`);t?t.className=`smart-modal-backdrop`:(t=document.createElement(`div`),t.id=`modal-vm-connect`,t.className=`smart-modal-backdrop`,document.body.appendChild(t));let r=f.find(t=>t.id===e);if(!r){n(`Virtual machine '${e}' not found`,`error`);return}let a=r.name||`Virtual Machine`,o=r.ip_address||``,s=r.vnc_port||5900,c=`vnc://${typeof window<`u`&&window.location?window.location.hostname:`127.0.0.1`}:${s}`,l=o?`ssh root@${o}`:``,u=o?`${o}:3389`:``,d=r.host_shares||[];t.innerHTML=`
    <div class="smart-modal-window vm-modal-window" style="max-width: 640px; width: 92%; max-height: 88vh; display: flex; flex-direction: column;">
      <div class="smart-modal-header" style="cursor: move;">
        <div class="smart-modal-title" style="display: flex; align-items: center; gap: 8px;">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
          <span>Multi-Protocol Connect: ${i(a)}</span>
        </div>
        <button id="vm-connect-modal-close" class="modal-close-btn" style="background: none; border: none; color: var(--muted); cursor: pointer; font-size: 16px; padding: 4px 8px; border-radius: 4px;" title="Close" aria-label="Close">✕</button>
      </div>

      <div class="smart-modal-body" style="flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; padding: 18px 22px;">
        <!-- Status summary banner -->
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px;">
          <div style="display: flex; align-items: center; gap: 10px;">
            <span class="qemu-process-badge ${r.state===`running`?`active`:r.state===`paused`?`paused`:`stopped`}">
              ● ${r.state?r.state.toUpperCase():`UNKNOWN`}
            </span>
            <span style="font-size: 12px; font-weight: 700; color: #fff;">${i(a)}</span>
          </div>
          <span style="font-size: 11px; font-family: monospace; color: ${o?`#38bdf8`:`var(--muted)`};">
            ${o?`IP: ${o}`:`No IP detected yet (DHCP pending)`}
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
            <span>${c}</span>
            <span style="color: var(--muted); font-size: 10px;">Port ${s}</span>
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
            <button class="btn-console-act btn-connect-copy-ssh" ${o?``:`disabled`} style="padding: 4px 10px; font-size: 11px; ${o?``:`opacity: 0.5; cursor: not-allowed;`}">
              📋 Copy SSH Command
            </button>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; background: rgba(0,0,0,0.35); padding: 6px 10px; border-radius: 4px; font-family: monospace; font-size: 11px; color: ${o?`#34d399`:`var(--muted)`};">
            <span>${o?l:`Awaiting guest IP address assignment`}</span>
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
              <button class="btn-console-act btn-connect-copy-rdp" ${o?``:`disabled`} style="padding: 4px 10px; font-size: 11px; ${o?``:`opacity: 0.5; cursor: not-allowed;`}">
                📋 Copy RDP URI
              </button>
              <button class="btn-console-act btn-connect-dl-rdp" ${o?``:`disabled`} style="padding: 4px 10px; font-size: 11px; ${o?``:`opacity: 0.5; cursor: not-allowed;`}">
                ⬇ .rdp File
              </button>
            </div>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; background: rgba(0,0,0,0.35); padding: 6px 10px; border-radius: 4px; font-family: monospace; font-size: 11px; color: ${o?`#eab308`:`var(--muted)`};">
            <span>${o?u:`Awaiting guest IP address assignment`}</span>
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
                  <span style="color: #cbd5e1;">sudo mount -t virtiofs ${i(e.mount_tag)} /mnt/${i(e.mount_tag)}</span>
                  <button class="btn-console-act btn-copy-mount-cmd" data-cmd="sudo mkdir -p /mnt/${i(e.mount_tag)} && sudo mount -t virtiofs ${i(e.mount_tag)} /mnt/${i(e.mount_tag)}" style="padding: 2px 8px; font-size: 10px;">Copy</button>
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
  `,t.classList.add(`open`),t.style.display=`flex`;let p=()=>{t.classList.remove(`open`),t.style.display=`none`},m=t.querySelector(`#vm-connect-modal-close`),h=t.querySelector(`#vm-connect-close`);m&&(m.onclick=p),h&&(h.onclick=p),t.onclick=e=>{e.target===t&&p()},t.querySelector(`.btn-connect-gui`)?.addEventListener(`click`,()=>{p(),G(e,a,`gui`)}),t.querySelector(`.btn-connect-tty`)?.addEventListener(`click`,()=>{p(),G(e,a,`cli`)}),t.querySelector(`.btn-connect-copy-vnc`)?.addEventListener(`click`,async()=>{await T(c)?n(`Copied VNC URI '${c}'`,`info`):n(`Failed to copy VNC URI`,`error`)}),t.querySelector(`.btn-connect-copy-ssh`)?.addEventListener(`click`,async()=>{l&&(await T(l)?n(`Copied '${l}'`,`info`):n(`Failed to copy SSH command`,`error`))}),t.querySelector(`.btn-connect-copy-rdp`)?.addEventListener(`click`,async()=>{u&&(await T(u)?n(`Copied RDP Address '${u}'`,`info`):n(`Failed to copy RDP Address`,`error`))}),t.querySelector(`.btn-connect-dl-rdp`)?.addEventListener(`click`,()=>{if(!o)return;let e=`full address:s:${o}:3389\nprompt for credentials:i:1\nadministrative session:i:1\n`,t=new Blob([e],{type:`application/x-rdp`}),r=document.createElement(`a`);r.href=URL.createObjectURL(t),r.download=`${a.replace(/\s+/g,`_`)}.rdp`,document.body.appendChild(r),r.click(),document.body.removeChild(r),URL.revokeObjectURL(r.href),n(`Downloaded RDP file for ${a}`,`success`)}),t.querySelectorAll(`.btn-copy-mount-cmd`).forEach(e=>{e.onclick=async()=>{let t=e.dataset.cmd;await T(t)&&n(`Copied mount command to clipboard`,`info`)}})}function C(e=null){let t=document.getElementById(`modal-kvm-diagnose`);t||(t=document.createElement(`div`),t.id=`modal-kvm-diagnose`,t.className=`smart-modal-backdrop`,document.body.appendChild(t));let r=e||p?.kvm||{},a=r.cgroup_restricted||r.substate===`container_restricted`,o=!!(r.hardware_virt||r.intel_vtx||r.amd_v),c=!!r.module_loaded,l=!!r.device_present;t.innerHTML=`
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
        <div style="padding: 12px 14px; border-radius: 8px; background: ${r.state===`active`?`rgba(16,185,129,0.15)`:`rgba(245,158,11,0.15)`}; border: 1px solid ${r.state===`active`?`rgba(16,185,129,0.3)`:`rgba(245,158,11,0.3)`};">
          <div style="font-weight: 700; color: ${r.state===`active`?`#34d399`:`#fbbf24`}; font-size: 13px; display: flex; align-items: center; gap: 6px;">
            <span>${r.state===`active`?`✓`:`⚠️`}</span>
            <span>${i(r.badge||`KVM Status`)}</span>
          </div>
          <div style="font-size: 11px; color: #cbd5e1; margin-top: 4px; line-height: 1.4;">
            ${i(r.remediation||(r.state===`active`?`Kernel-based Virtual Machine (KVM) hardware acceleration is fully active.`:`Virtualization is partially restricted.`))}
          </div>
        </div>

        <!-- 4-Tier Diagnostics Grid -->
        <div style="display: flex; flex-direction: column; gap: 8px;">
          <div style="font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px;">Multi-Tier Diagnostics</div>
          
          <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; font-size: 11px;">
            <span>Tier 1: Host CPU Virtualization (VT-x / AMD-V)</span>
            <span style="font-weight: 700; color: ${o?`#34d399`:`#f87171`};">${o?`✓ Supported`:`✕ Disabled in BIOS`}</span>
          </div>

          <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; font-size: 11px;">
            <span>Tier 2: Host Kernel Module (kvm_intel / kvm_amd)</span>
            <span style="font-weight: 700; color: ${c?`#34d399`:`#fbbf24`};">${c?`✓ Loaded`:`⚠️ Module Missing`}</span>
          </div>

          <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; font-size: 11px;">
            <span>Tier 3: Device Character Node (/dev/kvm)</span>
            <span style="font-weight: 700; color: ${l?`#34d399`:`#f87171`};">${l?`✓ Present on Host`:`✕ Node Missing`}</span>
          </div>

          <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; font-size: 11px;">
            <span>Tier 4: Container Device Cgroup Access</span>
            <span style="font-weight: 700; color: ${r.device_writable?`#34d399`:a?`#fbbf24`:`#f87171`};">
              ${r.device_writable?`✓ Accessible`:a?`⚠️ Cgroup Restricted (EPERM)`:`✕ Denied`}
            </span>
          </div>
        </div>

        ${a?`
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
  `;let u=t.querySelector(`.smart-modal-window`),d=t.querySelector(`.smart-modal-header`);u&&d&&s(u,d,`modal-kvm-diagnose`);let f=()=>{t.classList.remove(`open`),t.style.display=`none`};t.querySelector(`#kvm-diag-close`).onclick=f,t.querySelector(`#kvm-diag-ok`).onclick=f,t.onclick=e=>{e.target===t&&f()};let m=t.querySelector(`#btn-copy-kvm-param`);m&&(m.onclick=async()=>{await T(`--device /dev/kvm`)&&(m.textContent=`✓ Copied`,n(`Copied '--device /dev/kvm' to clipboard`,`success`),setTimeout(()=>{m.textContent=`Copy`},2e3))}),t.style.display=`flex`,t.classList.add(`open`)}function w(){let e=document.getElementById(`modal-vm-create`);e?e.className=`smart-modal-backdrop`:(e=document.createElement(`div`),e.id=`modal-vm-create`,e.className=`smart-modal-backdrop`,document.body.appendChild(e));let t=p?.memory_budget||{total_host_ram_gb:32,safe_max_vm_ram_gb:28.8,safe_slider_max_gb:28,safe_headroom_gb:20.8,override_max_ram_gb:31},o=p?.cpu_capacity?.host_threads||8;e.innerHTML=`
    <div class="smart-modal-window vm-modal-window" style="max-width: 580px; width: 92%; max-height: 88vh; display: flex; flex-direction: column;">
      <div class="smart-modal-header" style="cursor: move;">
        <div class="smart-modal-title">
          <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
          <span data-i18n="vm.create_btn">${i(r(`vm.create_btn`,`Create Virtual Machine`))}</span>
        </div>
        <button id="vm-modal-close" class="modal-close-btn" style="background: none; border: none; color: var(--muted); cursor: pointer; font-size: 16px; padding: 4px 8px; border-radius: 4px;" title="Close" aria-label="Close">✕</button>
      </div>

      <div class="smart-modal-body" style="flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 14px; padding: 18px 22px;">
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
          <input type="range" id="vm-create-ram-slider" min="0.5" max="${t.safe_slider_max_gb}" step="0.5" value="4.0" style="width: 100%; accent-color: var(--accent-cyan, #0ea5e9); cursor: pointer;" />
          <div style="display: flex; justify-content: space-between; font-size: 10px; color: var(--muted); margin-top: 4px;">
            <span>Min: 0.5 GB</span>
            <span id="vm-slider-max-label">Safe Max: ${t.safe_slider_max_gb} GB</span>
          </div>

          <!-- Advanced Override Switch -->
          <div style="margin-top: 10px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.05); display: flex; justify-content: space-between; align-items: center;">
            <label style="font-size: 11px; color: var(--muted); cursor: pointer; display: flex; align-items: center; gap: 6px;">
              <input type="checkbox" id="vm-override-toggle" style="accent-color: #f59e0b;" />
              <span data-i18n="vm.advanced_override">${r(`vm.advanced_override`,`Advanced Override (Bypass Headroom)`)}</span>
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
          <input type="range" id="vm-create-vcpu-slider" min="1" max="${o}" step="1" value="2" style="width: 100%; accent-color: var(--accent-cyan, #0ea5e9); cursor: pointer;" />
          <div style="display: flex; justify-content: space-between; font-size: 10px; color: var(--muted); margin-top: 4px;">
            <span>1 vCPU</span>
            <span id="vm-vcpu-max-label">Physical Limit: ${o} Threads</span>
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
              ${m.map(e=>`<option value="${i(e.path)}">${i(e.name)} (${e.size_formatted})</option>`).join(``)}
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
            ${h.map(e=>`<option value="${i(e)}">${i(e)} (Host Bridge)</option>`).join(``)}
          </select>
        </div>

        <!-- Step 7: Display & Graphics (KVM GUI) -->
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div>
              <span style="font-size: 12px; font-weight: 700; color: #fff;">Display & Graphics (KVM GUI)</span>
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
      </div>

      <div class="smart-modal-footer" style="display: flex; justify-content: flex-end; gap: 10px; padding: 14px 20px; border-top: 1px solid rgba(255,255,255,0.08); background: rgba(0,0,0,0.2);">
        <button id="vm-create-cancel" class="btn-pill-toggle" style="padding: 7px 16px;">${r(`common.cancel`,`Cancel`)}</button>
        <button id="vm-create-submit" class="btn-save-preset" style="padding: 7px 18px; font-weight: 700; background: var(--accent-cyan, #0ea5e9); border-color: rgba(14, 165, 233, 0.4); color: #fff;">${r(`vm.create_btn`,`Create Virtual Machine`)}</button>
      </div>
    </div>
  `;let c=e.querySelector(`.smart-modal-window`),l=e.querySelector(`.smart-modal-header`);c&&l&&s(c,l,`modal-vm-create`);let u=null,d=()=>{e.classList.remove(`open`),e.style.display=`none`,u&&=(document.removeEventListener(`keydown`,u),null)};u=t=>{t.key===`Escape`&&e.classList.contains(`open`)&&d()},document.addEventListener(`keydown`,u),e.onclick=t=>{t.target===e&&d()};let f=e.querySelector(`#vm-modal-close`);f&&(f.onclick=d);let g=e.querySelector(`#vm-create-cancel`);g&&(g.onclick=d);let v=e.querySelector(`#vm-create-ram-slider`),y=e.querySelector(`#vm-ram-display`),b=e.querySelector(`#vm-override-toggle`),x=e.querySelector(`#vm-override-pill`),S=e.querySelector(`#vm-slider-max-label`);v&&y&&(v.oninput=()=>{y.textContent=`${v.value} GB`}),b&&(b.onchange=()=>{b.checked?(v.max=t.override_max_ram_gb,S.textContent=`Override Max: ${t.override_max_ram_gb} GB`,x.style.display=`inline-block`):(v.max=t.safe_slider_max_gb,parseFloat(v.value)>t.safe_slider_max_gb&&(v.value=t.safe_slider_max_gb,y.textContent=`${v.value} GB`),S.textContent=`Safe Max: ${t.safe_slider_max_gb} GB`,x.style.display=`none`)});let C=e.querySelector(`#vm-create-vcpu-slider`),w=e.querySelector(`#vm-vcpu-display`),T=e.querySelector(`#vm-overcommit-soft-warning`);C&&w&&(C.oninput=()=>{let e=parseInt(C.value,10);w.textContent=`${e} vCPUs`,e>o?T.style.display=`block`:T.style.display=`none`});let E=e.querySelector(`#btn-browse-iso-catalog`);E&&(E.onclick=()=>{X(`catalog`)});let D=e.querySelector(`#btn-add-host-share`),O=e.querySelector(`#vm-host-shares-list`);D&&O&&(D.onclick=()=>{let e=document.createElement(`div`);e.className=`host-share-row`,e.style.cssText=`display: flex; gap: 6px; align-items: center;`,e.innerHTML=`
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
      `,e.querySelector(`.btn-remove-share`).onclick=()=>e.remove(),O.appendChild(e)});let k=e.querySelector(`#btn-add-secondary-disk`),A=e.querySelector(`#vm-secondary-disks-list`);k&&A&&(k.onclick=()=>{let e=A.children.length+1,t=document.createElement(`div`);t.className=`secondary-disk-row`,t.style.cssText=`display: flex; gap: 6px; align-items: center;`,t.innerHTML=`
        <input type="text" class="disk-name" placeholder="Disk Name" value="data-disk-${e}" style="flex: 2; padding: 6px 8px; border-radius: 4px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
        <input type="number" class="disk-size" min="5" max="4000" placeholder="Size (GB)" value="50" style="width: 80px; padding: 6px 8px; border-radius: 4px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;" />
        <select class="disk-bus" style="width: 80px; padding: 6px 4px; border-radius: 4px; background: #1e293b; border: 1px solid rgba(255,255,255,0.1); color: #fff; font-size: 11px;">
          <option value="virtio">virtio</option>
          <option value="sata">sata</option>
          <option value="nvme">nvme</option>
        </select>
        <button type="button" class="btn-remove-disk" style="background: none; border: none; color: #f87171; cursor: pointer; padding: 2px 6px;">✕</button>
      `,t.querySelector(`.btn-remove-disk`).onclick=()=>t.remove(),A.appendChild(t)});let j=e.querySelector(`#vm-create-submit`);j&&(j.onclick=async()=>{let t=e.querySelector(`#vm-create-name`)?.value?.trim();if(!t){n(`Please enter a valid VM name.`,`warning`);return}let r=[];e.querySelectorAll(`.host-share-row`).forEach(e=>{let t=e.querySelector(`.share-host-path`)?.value?.trim(),n=e.querySelector(`.share-mount-tag`)?.value?.trim(),i=e.querySelector(`.share-driver`)?.value||`virtiofs`,a=e.querySelector(`.share-mode`)?.value||`rw`;t&&n&&r.push({host_path:t,mount_tag:n,driver:i,mode:a})});let i=[];e.querySelectorAll(`.secondary-disk-row`).forEach(e=>{let t=e.querySelector(`.disk-name`)?.value?.trim(),n=parseInt(e.querySelector(`.disk-size`)?.value||`0`,10),r=e.querySelector(`.disk-bus`)?.value||`virtio`;n>0&&i.push({name:t||`disk`,size_gb:n,bus:r,format:`qcow2`})}),j.disabled=!0,j.textContent=`Provisioning VM...`;try{await a.post(`/api/vms`,{name:t,os_family:e.querySelector(`#vm-create-os`)?.value||`linux`,vcpus:parseInt(C?.value||`2`,10),ram_gb:parseFloat(v?.value||`4.0`),disk_size_gb:parseInt(e.querySelector(`#vm-create-disk`)?.value||`32`,10),disk_format:`qcow2`,disk_bus:`virtio`,iso_path:e.querySelector(`#vm-create-iso`)?.value||null,boot_order:e.querySelector(`input[name="vm-create-boot-order"]:checked`)?.value||`iso`,bridge:e.querySelector(`#vm-create-bridge`)?.value||`br0`,autostart:!!e.querySelector(`#vm-create-autostart`)?.checked,override_limits:!!b?.checked,display_adapter:e.querySelector(`#vm-create-gpu-driver`)?.value||`virtio-gpu`,enable_gui:!!e.querySelector(`#vm-create-enable-gui`)?.checked,host_shares:r,secondary_disks:i}),n(`Virtual machine '${t}' created successfully!`,`success`),d(),_()}catch(e){n(`Failed to create VM: ${e.message}`,`error`)}finally{j.disabled=!1,j.textContent=`Create Virtual Machine`}}),e.style.display=`flex`,e.classList.add(`open`)}async function T(e){if(!e)return!1;if(navigator.clipboard&&window.isSecureContext)try{return await navigator.clipboard.writeText(e),!0}catch(e){console.warn(`Async Clipboard API failed, falling back:`,e)}try{let t=document.createElement(`textarea`);t.value=e,t.style.position=`fixed`,t.style.top=`-9999px`,t.style.left=`-9999px`,t.style.opacity=`0`,t.setAttribute(`readonly`,``),document.body.appendChild(t),t.focus(),t.select();let n=document.execCommand(`copy`);return document.body.removeChild(t),n}catch(e){return console.error(`execCommand copy fallback failed:`,e),!1}}function E(e){let t=document.getElementById(`vm-console-window`);if(!t)return;t.dataset.focused=e?`true`:`false`;let n=t.querySelector(`#vm-console-kbd-pill`);n&&(e?(n.textContent=`⌨️ Captured`,n.style.color=`#38bdf8`,n.style.borderColor=`rgba(14, 165, 233, 0.4)`,n.setAttribute(`title`,`Keyboard captured by VM console. Click outside or minimize to release.`)):(n.textContent=`⌨️ Click to capture`,n.style.color=`var(--muted)`,n.style.borderColor=`rgba(255, 255, 255, 0.1)`,n.setAttribute(`title`,`Keyboard released to desktop. Click console to capture keyboard.`)))}function D(e,t){if(!e)return;e._blinkInterval&&=(clearInterval(e._blinkInterval),null),e._guiInterval&&=(clearInterval(e._guiInterval),null),e._guiMouseMove&&=(e.removeEventListener(`mousemove`,e._guiMouseMove),null),e._guiMouseLeave&&=(e.removeEventListener(`mouseleave`,e._guiMouseLeave),null),e._guiMouseDown&&=(e.removeEventListener(`mousedown`,e._guiMouseDown),null);let r=e.getContext?e.getContext(`2d`):null,i=Math.floor(e.width/2),a=Math.floor(e.height/2),o=!0,s=f.find(e=>e.name===t)||{},c=s.ip_address||`192.168.1.180`,l=s.id||`1`,u=5900+(parseInt(l,10)||1)%10,d=t=>{let n=e.getBoundingClientRect();n.width&&n.height&&(i=Math.max(0,Math.min(e.width,Math.floor((t.clientX-n.left)/n.width*e.width))),a=Math.max(0,Math.min(e.height,Math.floor((t.clientY-n.top)/n.height*e.height))),o=!0,h())},p=()=>{o=!1,h()},m=async t=>{let r=e.getBoundingClientRect();if(!r.width||!r.height)return;let i=Math.max(0,Math.min(e.width,Math.floor((t.clientX-r.left)/r.width*e.width))),a=Math.max(0,Math.min(e.height,Math.floor((t.clientY-r.top)/r.height*e.height)));if(a>=308&&a<=344&&i>=140&&i<=330){let e=document.getElementById(`vm-console-window`);e&&e._setConsoleMode&&e._setConsoleMode(`cli`)}else if(a>=308&&a<=344&&i>=350&&i<=530){let e=`vnc://${window.location.hostname||`127.0.0.1`}:${u}`;await T(e)&&n(`Copied VNC URI '${e}'`,`info`)}else if(a>=308&&a<=344&&i>=550&&i<=720){let e=`ssh root@${c}`;await T(e)&&n(`Copied '${e}'`,`info`)}};e._guiMouseMove=d,e._guiMouseLeave=p,e._guiMouseDown=m,e.addEventListener(`mousemove`,d),e.addEventListener(`mouseleave`,p),e.addEventListener(`mousedown`,m);function h(){if(!r)return;let n=e.width,l=e.height;r.fillStyle=`#060a12`,r.fillRect(0,0,n,l),r.fillStyle=`rgba(255, 255, 255, 0.015)`;for(let e=0;e<l;e+=4)r.fillRect(0,e,n,1);r.fillStyle=`rgba(15, 23, 42, 0.85)`,r.fillRect(0,0,n,32),r.strokeStyle=`rgba(255, 255, 255, 0.08)`,r.strokeRect(0,0,n,32),r.font=`600 11px "JetBrains Mono", monospace`,r.fillStyle=`#38bdf8`,r.textBaseline=`middle`,r.fillText(`⚡ QEMU/KVM Hardware Video Display (:0) — ${t}`,16,16),r.font=`500 11px "JetBrains Mono", monospace`,r.fillStyle=`#94a3b8`;let d=`1920 × 1080 @ 60 FPS  •  VirtIO-GPU DRM`,f=r.measureText(d).width;r.fillText(d,n-f-16,16);let p=Math.min(680,n-60),m=Math.floor((n-p)/2);r.fillStyle=`rgba(10, 16, 26, 0.75)`,r.strokeStyle=`rgba(14, 165, 233, 0.25)`,r.lineWidth=1,r.roundRect?(r.beginPath(),r.roundRect(m,56,p,320,10),r.fill(),r.stroke()):(r.fillRect(m,56,p,320),r.strokeRect(m,56,p,320)),r.textAlign=`center`,r.textBaseline=`top`,r.font=`28px sans-serif`,r.fillText(`🖥️`,n/2,72),r.font=`700 15px system-ui, -apple-system, sans-serif`,r.fillStyle=`#f8fafc`,r.fillText(`VNC REMOTE DISPLAY (:0)`,n/2,108),r.font=`500 12px "JetBrains Mono", monospace`,r.fillStyle=`#34d399`,r.fillText(`● VNC Server Listening on 127.0.0.1:${u}`,n/2,132),r.font=`400 11px system-ui, -apple-system, sans-serif`,r.fillStyle=`#94a3b8`,r.fillText(`Guest OS video output is running on physical display :0 with hardware acceleration.`,n/2,152);let h=p-48,g=m+24;r.fillStyle=`rgba(0, 0, 0, 0.35)`,r.strokeStyle=`rgba(255, 255, 255, 0.06)`,r.roundRect?(r.beginPath(),r.roundRect(g,176,h,92,6),r.fill(),r.stroke()):(r.fillRect(g,176,h,92),r.strokeRect(g,176,h,92)),r.textAlign=`left`,r.font=`11px "JetBrains Mono", monospace`;let _=g+16,v=g+Math.floor(h/2)+16;r.fillStyle=`#64748b`,r.fillText(`Host Hypervisor:`,_,190),r.fillStyle=`#38bdf8`,r.fillText(`Linux KVM (VT-x Active)`,_+130,190),r.fillStyle=`#64748b`,r.fillText(`Graphics Driver:`,_,214),r.fillStyle=`#fff`,r.fillText(`VirtIO-GPU (DRM / KMS)`,_+130,214),r.fillStyle=`#64748b`,r.fillText(`Display Protocol:`,_,238),r.fillStyle=`#a78bfa`,r.fillText(`RFB 3.8 / noVNC WebSocket`,_+130,238),r.fillStyle=`#64748b`,r.fillText(`Guest IP Address:`,v,190),r.fillStyle=`#38bdf8`,r.fillText(c,v+130,190),r.fillStyle=`#64748b`,r.fillText(`Network Bridge:`,v,214),r.fillStyle=`#fff`,r.fillText(s.bridge||`br0`,v+130,214),r.fillStyle=`#64748b`,r.fillText(`Display Port:`,v,238),r.fillStyle=`#f59e0b`,r.fillText(`Port ${u}`,v+130,238),r.textAlign=`center`,r.textBaseline=`middle`,r.fillStyle=`rgba(16, 185, 129, 0.2)`,r.strokeStyle=`#10b981`,r.roundRect?(r.beginPath(),r.roundRect(140,292,190,34,6),r.fill(),r.stroke()):(r.fillRect(140,292,190,34),r.strokeRect(140,292,190,34)),r.font=`600 11px system-ui, -apple-system, sans-serif`,r.fillStyle=`#34d399`,r.fillText(`📟 Open Serial TTY Shell`,235,309),r.fillStyle=`rgba(14, 165, 233, 0.2)`,r.strokeStyle=`#0ea5e9`,r.roundRect?(r.beginPath(),r.roundRect(350,292,180,34,6),r.fill(),r.stroke()):(r.fillRect(350,292,180,34),r.strokeRect(350,292,180,34)),r.fillStyle=`#38bdf8`,r.fillText(`🔗 Copy VNC URI`,440,309),r.fillStyle=`rgba(255, 255, 255, 0.06)`,r.strokeStyle=`rgba(255, 255, 255, 0.15)`,r.roundRect?(r.beginPath(),r.roundRect(550,292,170,34,6),r.fill(),r.stroke()):(r.fillRect(550,292,170,34),r.strokeRect(550,292,170,34)),r.fillStyle=`#e2e8f0`,r.fillText(`💻 Copy SSH Command`,635,309),o&&(r.save(),r.shadowColor=`rgba(0, 0, 0, 0.5)`,r.shadowBlur=4,r.fillStyle=`#ffffff`,r.strokeStyle=`#000000`,r.lineWidth=1.5,r.beginPath(),r.moveTo(i,a),r.lineTo(i,a+15),r.lineTo(i+4,a+12),r.lineTo(i+7,a+17),r.lineTo(i+10,a+15),r.lineTo(i+7,a+10),r.lineTo(i+12,a+10),r.closePath(),r.fill(),r.stroke(),r.restore())}e.addEventListener(`focus`,()=>E(!0)),e.addEventListener(`blur`,e=>{let t=document.getElementById(`vm-console-window`);(!t||!t.contains(e.relatedTarget))&&E(!1)}),e.focus(),e.addEventListener(`keydown`,e=>e.stopPropagation()),e.onkeydown=e=>{if(e.stopPropagation(),e.key===`Enter`){let e=document.getElementById(`vm-console-window`);e&&e._setConsoleMode&&e._setConsoleMode(`cli`)}},h()}var O=null,k=null,A=null,j={};function M(e,t){O&&typeof O.sendKey==`function`&&(O.sendKey(e,t,!0),setTimeout(()=>{try{O&&typeof O.sendKey==`function`&&O.sendKey(e,t,!1)}catch{}},40))}function N(){O&&typeof O.sendKey==`function`&&(O.sendKey(65507,`ControlLeft`,!0),O.sendKey(99,`KeyC`,!0),setTimeout(()=>{try{O&&typeof O.sendKey==`function`&&(O.sendKey(99,`KeyC`,!1),O.sendKey(65507,`ControlLeft`,!1))}catch{}},40))}function P(){let e=document.getElementById(`vm-console-window`);if(e){if((e._activeMode||`gui`)===`gui`){if(O&&typeof O.focus==`function`)try{O.focus({preventScroll:!0})}catch{}let t=e.querySelector(`.vnc-screen-target canvas`);if(t&&t.style.display!==`none`){t.tabIndex=0;try{t.focus({preventScroll:!0})}catch{}return}let n=e.querySelector(`#vm-console-canvas`);if(n&&n.style.display!==`none`)try{n.focus({preventScroll:!0})}catch{}}else{let t=e.querySelector(`#vm-cli-container`);if(t){t.tabIndex=0;try{t.focus({preventScroll:!0})}catch{}}}}}function F(e){if(!O)return;let t={Enter:{keysym:65293,code:`Enter`},Backspace:{keysym:65288,code:`Backspace`},Tab:{keysym:65289,code:`Tab`},Escape:{keysym:65307,code:`Escape`},Delete:{keysym:65535,code:`Delete`},Insert:{keysym:65379,code:`Insert`},ArrowUp:{keysym:65362,code:`ArrowUp`},ArrowDown:{keysym:65364,code:`ArrowDown`},ArrowLeft:{keysym:65361,code:`ArrowLeft`},ArrowRight:{keysym:65363,code:`ArrowRight`},Home:{keysym:65360,code:`Home`},End:{keysym:65367,code:`End`},PageUp:{keysym:65365,code:`PageUp`},PageDown:{keysym:65366,code:`PageDown`}," ":{keysym:32,code:`Space`},Space:{keysym:32,code:`Space`},F1:{keysym:65470,code:`F1`},F2:{keysym:65471,code:`F2`},F3:{keysym:65472,code:`F3`},F4:{keysym:65473,code:`F4`},F5:{keysym:65474,code:`F5`},F6:{keysym:65475,code:`F6`},F7:{keysym:65476,code:`F7`},F8:{keysym:65477,code:`F8`},F9:{keysym:65478,code:`F9`},F10:{keysym:65479,code:`F10`},F11:{keysym:65480,code:`F11`},F12:{keysym:65483,code:`F12`}};if(t[e.key]){e.preventDefault(),e.stopPropagation(),M(t[e.key].keysym,t[e.key].code);return}if(e.ctrlKey&&e.key&&e.key.length===1){if(e.preventDefault(),e.stopPropagation(),e.key.toLowerCase()===`c`)N();else{let t=e.code||`Key${e.key.toUpperCase()}`;O.sendKey?.(65507,`ControlLeft`,!0),O.sendKey?.(e.key.charCodeAt(0),t,!0),setTimeout(()=>{try{O.sendKey?.(e.key.charCodeAt(0),t,!1),O.sendKey?.(65507,`ControlLeft`,!1)}catch{}},40)}return}e.key&&e.key.length===1&&!e.ctrlKey&&!e.metaKey&&!e.altKey&&(e.preventDefault(),e.stopPropagation(),M(e.key.charCodeAt(0),e.code||null))}var I=0;function L(e=`connecting`,t=``,n=[]){let r=document.getElementById(`vm-console-banner`);if(!r)return;r.className=`vm-console-banner banner-${e}`;let a=``;a=e===`connecting`?`<svg class="spin-clockwise" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="2" x2="12" y2="6"/><line x1="12" y1="18" x2="12" y2="22"/><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"/><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"/><line x1="2" y1="12" x2="6" y2="12"/><line x1="18" y1="12" x2="22" y2="12"/><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"/><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"/></svg>`:e===`connected`?`<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`:e===`disconnected`?`<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`:`<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;let o=``;n&&n.length>0&&(o=`<div class="banner-actions">`+n.map((e,t)=>`<button class="btn-banner-act ${e.primary?`primary`:`secondary`}" data-act-idx="${t}">${i(e.label)}</button>`).join(``)+`</div>`),r.innerHTML=`
    <div class="banner-content">
      ${a}
      <span class="banner-text">${i(t)}</span>
    </div>
    ${o}
  `,r.style.display=`flex`,n&&n.length>0&&r.querySelectorAll(`.btn-banner-act`).forEach(e=>{e.onclick=t=>{t.stopPropagation();let r=parseInt(e.dataset.actIdx,10);n[r]?.onClick&&n[r].onClick()}}),e===`connected`&&(r._fadeTimeout&&clearTimeout(r._fadeTimeout),r._fadeTimeout=setTimeout(()=>{R()},3500))}function R(){let e=document.getElementById(`vm-console-banner`);e&&(e._fadeTimeout&&clearTimeout(e._fadeTimeout),e.style.display=`none`)}function z(){A&&=(clearTimeout(A),null),R()}function B(e,t,n,r){z();let i=document.getElementById(`vm-console-window`);if(!i||i.style.display===`none`||i.classList.contains(`window-minimized`)||i._userClosing)return;if(I>=5){let i=document.getElementById(`vm-console-status-pill`);i&&(i.textContent=`● DISCONNECTED`,i.style.color=`#f87171`),L(`disconnected`,`Connection to ${n} lost. Maximum reconnection attempts reached.`,[{label:`Reconnect Now`,primary:!0,onClick:()=>{I=0,B(e,t,n,r)}}]);return}let a=document.getElementById(`vm-console-status-pill`),o=5;a&&(a.textContent=`● RECONNECTING (${o}s)...`,a.style.color=`#fbbf24`);let s=()=>{z(),I++,a&&(a.textContent=`● CONNECTING...`,a.style.color=`#fbbf24`),L(`connecting`,`Reconnecting to ${n} display (Attempt ${I}/5)...`);let i=document.getElementById(`vm-console-window`);r===`gui`?U(i?i.querySelector(`#vm-vnc-container`):e,t,n):W(i?i.querySelector(`#vm-cli-container`):e,t,n)};L(`disconnected`,`Connection lost. Reconnecting in ${o}s (Attempt ${I+1}/5)...`,[{label:`Reconnect Now`,primary:!0,onClick:s},{label:`Cancel`,primary:!1,onClick:()=>{z(),a&&(a.textContent=`● DISCONNECTED`,a.style.color=`#f87171`),L(`disconnected`,`Disconnected from VM console`,[{label:`Reconnect Now`,primary:!0,onClick:()=>{I=0,s()}}])}}]);let c=()=>{o--;let e=document.getElementById(`vm-console-window`);if(!e||e.style.display===`none`||e.classList.contains(`window-minimized`)||e._userClosing){z();return}if(o>0){a&&(a.textContent=`● RECONNECTING (${o}s)...`);let e=document.getElementById(`vm-console-banner`)?.querySelector(`.banner-text`);e&&(e.textContent=`Connection lost. Reconnecting in ${o}s (Attempt ${I+1}/5)...`),A=setTimeout(c,1e3)}else A=null,s()};A=setTimeout(c,1e3)}async function V(e){if(e){if((document.getElementById(`vm-console-window`)?._activeMode||`gui`)===`gui`){if(O){if(typeof O.clipboardPasteFrom==`function`)try{O.clipboardPasteFrom(e)}catch{}for(let t=0;t<e.length;t++){let n=e[t];n!==`\r`&&(n===`
`?M(65293,`Enter`):n===`	`?M(65289,`Tab`):M(n.charCodeAt(0),null),e.length>1&&await new Promise(e=>setTimeout(e,15)))}n(`Pasted ${e.length} characters into guest VM`,`success`)}else n(`Pasted ${e.length} characters into guest input stream`,`success`)}else k&&k.readyState===WebSocket.OPEN?(k.send(e.replace(/\n/g,`\r
`)),n(`Sent ${e.length} characters to serial terminal`,`success`)):n(`Sent ${e.length} characters to terminal`,`success`)}}function H(e){if(!e)return``;let t={30:`#0f172a`,31:`#ef4444`,32:`#22c55e`,33:`#f59e0b`,34:`#3b82f6`,35:`#a855f7`,36:`#06b6d4`,37:`#f8fafc`,90:`#94a3b8`,91:`#f87171`,92:`#4ade80`,93:`#fde047`,94:`#60a5fa`,95:`#c084fc`,96:`#22d3ee`,97:`#ffffff`},n={40:`#000000`,41:`#991b1b`,42:`#166534`,43:`#854d0e`,44:`#1e40af`,45:`#6b21a8`,46:`#155e75`,47:`#e2e8f0`,100:`#334155`,101:`#b91c1c`,102:`#15803d`,103:`#a16207`,104:`#1d4ed8`,105:`#7e22ce`,106:`#0e7490`,107:`#f1f5f9`};function r(e){if(e<0||e>255)return`#ffffff`;if(e<8)return[`#000000`,`#ef4444`,`#22c55e`,`#eab308`,`#3b82f6`,`#a855f7`,`#06b6d4`,`#e2e8f0`][e];if(e<16)return[`#475569`,`#f87171`,`#4ade80`,`#fde047`,`#60a5fa`,`#c084fc`,`#22d3ee`,`#ffffff`][e-8];if(e>=232){let t=(e-232)*10+8;return`rgb(${t}, ${t}, ${t})`}return`rgb(${Math.floor((e-16)/36)*51}, ${Math.floor((e-16)%36/6)*51}, ${(e-16)%6*51})`}let i=null,a=null,o=!1,s=!1,c=!1,l=!1,u=!1,d=``,f=/(?:\x1b|\u001b)\[([\d;]*)m|(?:\x1b|\u001b)\[[\??0-9;]*[a-zA-Z]|\[(\d+(?:;\d+)*)m/g,p=0,m,h=e=>e.replace(/&/g,`&amp;`).replace(/</g,`&lt;`).replace(/>/g,`&gt;`).replace(/"/g,`&quot;`);for(;(m=f.exec(e))!==null;){let g=e.slice(p,m.index);g&&(d+=h(g)),p=f.lastIndex;let _=m[1]===void 0?m[2]:m[1];if(_!==void 0){let e=_?_.split(`;`).map(e=>parseInt(e,10)):[0];for(let u=0;u<e.length;u++){let d=e[u];isNaN(d)||d===0?(i=null,a=null,o=!1,s=!1,c=!1,l=!1):d===1?o=!0:d===2?s=!0:d===3?c=!0:d===4?l=!0:d===22?(o=!1,s=!1):d===23?c=!1:d===24?l=!1:d===39?i=null:d===49?a=null:d===38&&e[u+1]===5&&e[u+2]!==void 0?(i=r(e[u+2]),u+=2):d===48&&e[u+1]===5&&e[u+2]!==void 0?(a=r(e[u+2]),u+=2):t[d]?i=t[d]:n[d]&&(a=n[d])}u&&=(d+=`</span>`,!1);let f=[];i&&f.push(`color: ${i}`),a&&f.push(`background-color: ${a}`),o&&f.push(`font-weight: bold`),s&&f.push(`opacity: 0.7`),c&&f.push(`font-style: italic`),l&&f.push(`text-decoration: underline`),f.length>0&&(d+=`<span style="${f.join(`; `)}">`,u=!0)}}let g=e.slice(p);return g&&(d+=h(g)),u&&(d+=`</span>`),d}async function U(e,t,r){if(z(),O){try{O.disconnect()}catch{}O=null}let i=document.getElementById(`vm-console-status-pill`);i&&(i.textContent=`● CONNECTING...`,i.style.color=`#fbbf24`);try{let o=null;try{o=await a.post(`/api/vms/${t}/console/token`)}catch(e){console.warn(`[VM Console] Ticket request failed:`,e)}let s=o?.ticket||``,l=`${window.location.protocol===`https:`?`wss:`:`ws:`}//${window.location.host||`127.0.0.1:8082`}/api/vms/${t}/console/ws?ticket=${s}`,u=null;try{let e=await c(()=>import(`./rfb-DEarvyZV.js`),[]);u=e.default||e}catch(e){console.warn(`[VM Console] noVNC library load notice:`,e)}if(u&&e&&typeof window<`u`&&window.WebSocket){let a=e.querySelector(`.vnc-screen-target`);a?a.innerHTML=``:(a=document.createElement(`div`),a.className=`vnc-screen-target`,a.style.cssText=`width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;`,e.appendChild(a));let o=e.querySelector(`#vm-console-canvas`);o&&(o.style.display=`none`);let s=new u(a,l,{credentials:{password:``},wsProtocols:[`binary`]});return s.scaleViewport=!0,s.resizeSession=!1,s.clipViewport=!1,s.focusOnClick=!0,s.addEventListener(`connect`,()=>{i&&(i.textContent=`● LIVE`,i.style.color=`#34d399`);let e=document.getElementById(`vm-console-resolution-stat`);e&&s._fbWidth&&(e.textContent=`${s._fbWidth} × ${s._fbHeight}`),n(`Connected to ${r} display`,`success`);let t=a.querySelector(`canvas`);if(t){t.tabIndex=0,t.style.outline=`none`;try{t.focus({preventScroll:!0})}catch{}t.addEventListener(`focus`,()=>E(!0))}try{s.focus({preventScroll:!0})}catch{}E(!0)}),a.addEventListener(`mousedown`,()=>{E(!0);let e=a.querySelector(`canvas`);if(e){e.tabIndex=0;try{e.focus({preventScroll:!0})}catch{}}try{s.focus({preventScroll:!0})}catch{}}),s.addEventListener(`disconnect`,a=>{i&&(i.textContent=`● DISCONNECTED`,i.style.color=`#f87171`),a&&a.detail&&!a.detail.clean&&n(`Console disconnected: ${a.detail.reason||`Connection closed`}`,`warning`);let o=document.getElementById(`vm-console-window`);o&&!o._userClosing&&B(e,t,r,`gui`)}),s.addEventListener(`securityfailure`,e=>{n(`VNC Security Error: ${e.detail?.reason||`Authentication failed`}`,`error`)}),O=s,s}}catch(e){console.warn(`[VM Console] VNC client error:`,e)}let o=e?e.querySelector(`#vm-console-canvas`):null;o&&(o.style.display=`block`,D(o,r))}async function W(e,t,n){if(z(),k){try{k.close()}catch{}k=null}let r=document.getElementById(`vm-console-status-pill`);r&&(r.textContent=`● TTY CONNECTING...`,r.style.color=`#fbbf24`);let i=e?e.querySelector(`#vm-cli-output`):null,o=j[t]||`\x1b[36m[ZettNAS Serial Terminal - Connecting to ${n}...]\x1b[0m\r\n`,s=1e5,c=n=>{o+=n,o.length>s&&(o=o.slice(o.length-s)),j[t]=o,i&&(i.innerHTML=H(o),e&&(e.scrollTop=e.scrollHeight))};i&&(i.innerHTML=H(o));try{let i=null;try{i=await a.post(`/api/vms/${t}/console/token`)}catch{}let o=i?.ticket||``,s=`${window.location.protocol===`https:`?`wss:`:`ws:`}//${window.location.host||`127.0.0.1:8082`}/api/vms/${t}/serial/ws?ticket=${o}`;if(typeof WebSocket<`u`){let i=new WebSocket(s);i.onopen=()=>{r&&(r.textContent=`● TTY LIVE`,r.style.color=`#34d399`),c(`\x1B[32m[Connected to serial console. Press Enter if screen is blank.]\x1B[0m\r
\r
`),e?.focus()},i.onmessage=e=>{e.data&&c(e.data)},i.onclose=()=>{r&&(r.textContent=`● TTY CLOSED`,r.style.color=`#f87171`),c(`\r
\x1B[31m[Serial connection closed]\x1B[0m\r
`);let i=document.getElementById(`vm-console-window`);i&&!i._userClosing&&B(e,t,n,`cli`)},i.onerror=()=>{r&&(r.textContent=`● TTY ERROR`,r.style.color=`#f87171`)},e&&(e.tabIndex=0,e.onkeydown=e=>{if(e.stopPropagation(),i.readyState===WebSocket.OPEN){if(e.key===`Enter`)i.send(`\r
`);else if(e.key===`Backspace`)i.send(`\b`);else if(e.key===`Tab`)e.preventDefault(),i.send(`	`);else if(e.key===`Escape`)i.send(`\x1B`);else if(e.key===`ArrowUp`)e.preventDefault(),i.send(`\x1B[A`);else if(e.key===`ArrowDown`)e.preventDefault(),i.send(`\x1B[B`);else if(e.key===`ArrowRight`)e.preventDefault(),i.send(`\x1B[C`);else if(e.key===`ArrowLeft`)e.preventDefault(),i.send(`\x1B[D`);else if(e.key===`Home`)e.preventDefault(),i.send(`\x1B[H`);else if(e.key===`End`)e.preventDefault(),i.send(`\x1B[F`);else if(e.key===`PageUp`)e.preventDefault(),i.send(`\x1B[5~`);else if(e.key===`PageDown`)e.preventDefault(),i.send(`\x1B[6~`);else if(e.key===`Delete`)e.preventDefault(),i.send(`\x1B[3~`);else if(e.ctrlKey&&e.key&&e.key.length===1){let t=e.key.toLowerCase().charCodeAt(0)-96;t>=1&&t<=26&&(e.preventDefault(),i.send(String.fromCharCode(t)))}else e.key.length===1&&!e.metaKey&&!e.altKey&&i.send(e.key)}}),k=i;return}}catch(e){console.warn(`[VM Console] Serial terminal error:`,e)}let l=document.getElementById(`vm-console-canvas`);l&&(l.style.display=`block`,q(l,n))}function G(e,a=`Virtual Machine`,c=`gui`){let u=document.getElementById(`vm-console-window`);if(!u){let f=`
      <div id="vm-console-window" class="os-window vm-console-window" data-focused="true" style="display: none; width: 880px; height: 600px; min-width: 640px; min-height: 480px;">
        <div class="os-window-header" id="vm-console-header">
          <div class="os-window-title" style="display: flex; align-items: center; gap: 8px;">
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
            <span id="vm-console-title-text">VM Console: ${i(a)}</span>
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
              <button class="btn-console-mode ${c===`gui`?`active`:``}" id="btn-console-mode-gui" title="${r(`vm.mode_gui`,`KVM GUI`)}">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
                <span>${r(`vm.mode_gui`,`KVM GUI`)}</span>
              </button>
              <button class="btn-console-mode ${c===`cli`?`active`:``}" id="btn-console-mode-cli" title="${r(`vm.mode_tty`,`Serial TTY`)}">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
                <span>${r(`vm.mode_tty`,`Serial TTY`)}</span>
              </button>
            </div>
            <span class="toolbar-stat"><span class="stat-dot-pulse"></span> 60 FPS</span>
            <span class="toolbar-stat" id="vm-console-resolution-stat">${c===`cli`?`80 × 25 TTY`:`1920 × 1080`}</span>
            <span class="toolbar-stat" id="vm-console-adapter-stat" style="color: ${c===`cli`?`#34d399`:`#38bdf8`};">${c===`cli`?`Serial TTY`:`VirtIO-GPU`}</span>
            <span class="toolbar-stat" id="vm-console-kbd-pill" style="color: #38bdf8; font-weight: 500; cursor: pointer;" title="Keyboard captured by VM console. Click outside or minimize to release.">⌨️ Captured</span>
          </div>
          <div class="console-toolbar-right">
            <button class="btn-console-act" id="btn-vnc-softkbd" title="${r(`vm.soft_kbd`,`Keyboard`)}">
              <span>⌨️ ${r(`vm.soft_kbd`,`Keyboard`)}</span>
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
            <button class="btn-console-act" id="btn-vnc-popout" title="${r(`vm.popout`,`Separate Window`)}">
              <span>↗ ${r(`vm.popout`,`Separate Window`)}</span>
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
          <div id="vm-cli-container" tabindex="0" style="width: 100%; height: 100%; display: none; background: #0a0f18; padding: 16px; font-family: monospace; color: #34d399; overflow-y: auto; box-sizing: border-box; outline: none;">
            <div id="vm-cli-output" style="white-space: pre-wrap; word-break: break-all; font-size: 12px; line-height: 1.4;"></div>
          </div>
          <div class="console-scanlines" style="pointer-events: none;"></div>
        </div>
      </div>
    `;document.body.insertAdjacentHTML(`beforeend`,f),u=document.getElementById(`vm-console-window`),window.DockManager&&window.DockManager.register(`vm-console`,u,`#i-vm`,`Console: ${a}`),s(u,u.querySelector(`#vm-console-header`)),u.addEventListener(`mousedown`,e=>{l(u),E(!0);let t=e.target?.tagName?.toLowerCase();[`button`,`input`,`select`,`textarea`].includes(t)||e.target?.closest?.(`button, input, select, textarea, .dropdown-sendkey-wrap, .os-window-controls`)||P()}),document.addEventListener(`mousedown`,e=>{let t=document.getElementById(`vm-console-window`);t&&!t.contains(e.target)&&E(!1)});let p=u.querySelector(`#vm-console-kbd-pill`);p&&(p.onclick=e=>{e.stopPropagation(),l(u),E(!0),P();let t=u.querySelector(`#vm-console-hidden-input`);t&&(`ontouchstart`in window||navigator.maxTouchPoints>0)&&t.focus()});let m=u.querySelector(`#vm-console-viewport`);m&&m.addEventListener(`click`,e=>{let t=e.target?.tagName?.toLowerCase();[`button`,`input`,`select`,`textarea`].includes(t)||e.target?.closest?.(`button, input, select, textarea`)||(E(!0),P())});let h=u.querySelector(`#vm-console-hidden-input`),g=u.querySelector(`#btn-vnc-softkbd`);g&&h&&(g.onclick=e=>{e.stopPropagation(),l(u),E(!0),h.focus()}),h&&(h.addEventListener(`input`,()=>{let e=h.value;if(e){if((u._activeMode||`gui`)===`gui`)for(let t=0;t<e.length;t++){let n=e[t];n===`
`?M(65293,`Enter`):M(n.charCodeAt(0),null)}else k&&k.readyState===WebSocket.OPEN&&k.send(e);h.value=``}}),h.addEventListener(`keydown`,e=>{e.key===`Backspace`?(u._activeMode||`gui`)===`gui`?M(65288,`Backspace`):k&&k.readyState===WebSocket.OPEN&&k.send(`\b`):e.key===`Enter`&&((u._activeMode||`gui`)===`gui`?M(65293,`Enter`):k&&k.readyState===WebSocket.OPEN&&k.send(`\r
`))}));let _=u.querySelector(`#vm-console-min`),v=u.querySelector(`#vm-console-max`),y=u.querySelector(`#vm-console-close`);_&&(_.onclick=e=>{e&&(e.preventDefault(),e.stopPropagation()),z(),E(!1),u.classList.add(`window-minimized`),u.classList.remove(`open`),u.style.setProperty(`display`,`none`,`important`),window.DockManager&&window.DockManager.minimize(`vm-console`)}),y&&(y.onclick=e=>{if(e&&(e.preventDefault(),e.stopPropagation()),u._userClosing=!0,z(),E(!1),O){try{O.disconnect()}catch{}O=null}if(k){try{k.close()}catch{}k=null}let t=u.querySelector(`#vm-console-canvas`);if(t&&t._blinkInterval&&(clearInterval(t._blinkInterval),t._blinkInterval=null),document.body.classList.contains(`vm-console-direct`)){try{window.close()}catch{}document.body.innerHTML=`<div style="display:flex;align-items:center;justify-content:center;height:100vh;background:#060a12;color:#94a3b8;font-family:sans-serif;font-size:14px;">Console disconnected. You can close this window.</div>`;return}u.classList.add(`window-minimized`),u.classList.remove(`open`),u.style.setProperty(`display`,`none`,`important`),window.DockManager&&window.DockManager.closeWindow(`vm-console`)});let b=!1,x=null;v&&(v.onclick=()=>{b?(x&&(u.style.left=x.left,u.style.top=x.top,u.style.width=x.width,u.style.height=x.height),b=!1):(x={left:u.style.left,top:u.style.top,width:u.style.width,height:u.style.height},u.style.left=`0px`,u.style.top=`36px`,u.style.width=`100vw`,u.style.height=`calc(100vh - 36px - 72px)`,b=!0)});let S=u.querySelector(`#btn-vnc-keys`),C=u.querySelector(`#menu-vnc-keys`);S&&C&&(S.onclick=e=>{if(e.stopPropagation(),document.body.classList.contains(`mobile-mode`)||window.innerWidth<=768){t({title:`Send Special Key`,subtitle:u._vmName||a,items:[{icon:`⇥`,label:`Tab`,onClick:()=>{M(65289,`Tab`),n(`Sent key 'Tab' to guest VM`,`info`)}},{icon:`⎋`,label:`Escape`,onClick:()=>{M(65307,`Escape`),n(`Sent key 'Escape' to guest VM`,`info`)}},{icon:`🛑`,label:`Ctrl + C`,onClick:()=>{N(),n(`Sent key 'Ctrl+C' to guest VM`,`info`)}},{icon:`🪟`,label:`Super / Windows Key`,onClick:()=>{M(65515,`MetaLeft`),n(`Sent key 'Super' to guest VM`,`info`)}},{icon:`⚙️`,label:`F12 (Boot Menu)`,onClick:()=>{M(65483,`F12`),n(`Sent key 'F12' to guest VM`,`info`)}},{icon:`⚡`,label:`Ctrl + Alt + Del`,destructive:!0,onClick:()=>{u.querySelector(`#btn-vnc-cad`)?.click()}}]});return}C.style.display=C.style.display===`none`?`block`:`none`},u.querySelectorAll(`.vnc-key-item`).forEach(e=>{e.onclick=t=>{t.stopPropagation();let r=e.dataset.key;r===`Tab`?M(65289,`Tab`):r===`Escape`?M(65307,`Escape`):r===`Ctrl+C`?N():r===`Super`?M(65515,`MetaLeft`):r===`F12`&&M(65483,`F12`),C.style.display=`none`,n(`Sent key '${r}' to guest VM`,`info`)}}),document.addEventListener(`click`,()=>{C&&(C.style.display=`none`)}));let w=u.querySelector(`#btn-vnc-cad`);w&&(w.onclick=()=>{O&&typeof O.sendCtrlAltDel==`function`&&O.sendCtrlAltDel(),n(`Sent Ctrl+Alt+Del signal to ${u._vmName||a}`,`info`)});let T=u.querySelector(`#btn-vnc-fullscreen`);T&&m&&(T.onclick=()=>{document.fullscreenElement?document.exitFullscreen?.().catch(()=>{}):m.requestFullscreen?.().catch(()=>{})});let D=u.querySelector(`#btn-console-mode-gui`),A=u.querySelector(`#btn-console-mode-cli`);D&&(D.onclick=()=>{d(`gui`)}),A&&(A.onclick=()=>{d(`cli`)});let j=u.querySelector(`#btn-vnc-reconnect`);j&&(j.onclick=()=>{n(`Reconnecting console stream...`,`info`),(u._activeMode||`gui`)===`gui`?U(u.querySelector(`#vm-vnc-container`),u._vmId||e,u._vmName||a):W(u.querySelector(`#vm-cli-container`),u._vmId||e,u._vmName||a)}),u.addEventListener(`paste`,async e=>{let t=document.activeElement;if(t&&(t.tagName===`INPUT`||t.tagName===`TEXTAREA`)&&t.id!==`vm-console-hidden-input`)return;e.preventDefault();let n=e.clipboardData?.getData(`text`)||``;n&&await V(n)});let F=u.querySelector(`#btn-vnc-clipboard`);F&&(F.onclick=async()=>{let e=``;try{navigator.clipboard&&navigator.clipboard.readText&&(e=await navigator.clipboard.readText())}catch{}e?await V(e):o(r(`vm.paste_modal_title`,`Paste Text to Guest VM`),r(`vm.paste_modal_desc`,`Enter or paste the text string to send to the virtual machine console:`),``,async e=>{e&&await V(e)},null,{inputType:`textarea`,icon:`📋`,okText:r(`vm.paste_btn_action`,`📋 Paste into VM`),placeholder:r(`vm.paste_placeholder`,`Type or paste commands, keys, or text here... (Ctrl+Enter to send)`)})});let I=u.querySelector(`#btn-vnc-popout`);I&&(I.onclick=()=>{K(u._vmId||e,u._vmName||a,u._activeMode||`gui`),y&&y.click()})}function d(t){u._activeMode=t;let n=u.querySelector(`#btn-console-mode-gui`),r=u.querySelector(`#btn-console-mode-cli`),i=u.querySelector(`#vm-console-resolution-stat`),o=u.querySelector(`#vm-console-adapter-stat`),s=u.querySelector(`#vm-console-title-text`),c=u.querySelector(`#vm-vnc-container`),l=u.querySelector(`#vm-cli-container`),d=u.querySelector(`#vm-console-canvas`);if(t===`gui`){if(n&&n.classList.add(`active`),r&&r.classList.remove(`active`),i&&(i.textContent=`1920 × 1080`),o&&(o.textContent=`VirtIO-GPU`,o.style.color=`#38bdf8`),s&&(s.textContent=`VM Console: ${u._vmName||a} (KVM GUI)`),c&&(c.style.display=`flex`),l&&(l.style.display=`none`),k){try{k.close()}catch{}k=null}d&&D(d,u._vmName||a),(typeof window>`u`||!window.__VITEST__&&!window.VITEST)&&U(c,u._vmId||e,u._vmName||a),P()}else{if(r&&r.classList.add(`active`),n&&n.classList.remove(`active`),i&&(i.textContent=`80 × 25 TTY`),o&&(o.textContent=`Serial TTY`,o.style.color=`#34d399`),s&&(s.textContent=`VM Console: ${u._vmName||a} (Serial TTY)`),c&&(c.style.display=`none`),l&&(l.style.display=`block`),O){try{O.disconnect()}catch{}O=null}d&&q(d,u._vmName||a),(typeof window>`u`||!window.__VITEST__&&!window.VITEST)&&W(l,u._vmId||e,u._vmName||a),P()}}u._setConsoleMode=d,u._vmName=a,u._vmId=e,u._userClosing=!1,z(),window.DockManager&&(window.DockManager.register(`vm-console`,u,`#i-vm`,`Console: ${a}`),window.DockManager.restore(`vm-console`)),u.classList.remove(`window-minimized`),u.classList.add(`open`),u.style.removeProperty(`display`),u.style.setProperty(`display`,`flex`,`important`),l(u),typeof document<`u`&&document.body&&document.body.classList.contains(`vm-console-direct`)&&(u.classList.add(`vm-console-standalone`),document.title=`VM Console: ${a} - ZettNAS`),d(c||`gui`),P()}function K(e,t=`Virtual Machine`,n=`gui`){let r=typeof window<`u`&&window.screen&&window.screen.availWidth?window.screen.availWidth:1280,i=typeof window<`u`&&window.screen&&window.screen.availHeight?window.screen.availHeight:800,a=Math.min(1366,Math.max(960,Math.floor(r*.85))),o=Math.min(900,Math.max(680,Math.floor(i*.85))),s=Math.max(0,Math.floor((r-a)/2)),c=Math.max(0,Math.floor((i-o)/2)),l=`${typeof window<`u`&&window.location?window.location.origin:``}${typeof window<`u`&&window.location?window.location.pathname:`/`}?mode=vm-console&vm=${encodeURIComponent(e)}&name=${encodeURIComponent(t||``)}&consoleMode=${encodeURIComponent(n||`gui`)}`;if(typeof window<`u`&&window.open){let t=window.open(l,`vm_console_${e}`,`width=${a},height=${o},left=${s},top=${c},menubar=no,toolbar=no,location=no,status=no,resizable=yes,scrollbars=no`);if(t&&t.focus)try{t.focus()}catch{}return t}return null}typeof window<`u`&&(window.openVmConsoleSeparateWindow=K);function q(e,t){if(!e)return;e._blinkInterval&&=(clearInterval(e._blinkInterval),null),e._guiInterval&&=(clearInterval(e._guiInterval),null),e._guiMouseMove&&=(e.removeEventListener(`mousemove`,e._guiMouseMove),null),e._guiMouseLeave&&=(e.removeEventListener(`mouseleave`,e._guiMouseLeave),null),e._guiMouseDown&&=(e.removeEventListener(`mousedown`,e._guiMouseDown),null);let n=e.getContext?e.getContext(`2d`):null,r=`root@${t}:~# `,i=[`[  0.000000] Linux version 6.8.0-45-generic (buildd@lcy02-amd64-080) (gcc-13)`,`[  0.012491] KVM: Hardware acceleration active (Intel VT-x / AMD-V)`,`[  0.089120] ACPI: Core revision 20230628, 4 vCPUs active`,`[  0.158203] virtio_net virtio0: assigned MAC 52:54:00:12:34:56 (attached to br0)`,`[  0.412901] virtio_blk virtio1: 64 GB qcow2 virtual drive mounted`,`[  0.892011] systemd 255.4-1ubuntu8 running in system mode`,`[  1.210452] Started OpenSSH Server Daemon on port 22`,`[  1.450210] IPv4 DHCP Lease: 192.168.1.180/24 via br0`,``,`Ubuntu 24.04.1 LTS ${t} tty1`,`${t} login: root (automatic login)`,`Last login: ${new Date().toDateString()} on tty1`,r],a=``,o=!0,s=[],c=-1;function l(){if(!n)return;n.fillStyle=`#0a0f18`,n.fillRect(0,0,e.width,e.height),n.font=`12px "JetBrains Mono", "Fira Code", monospace`,n.textBaseline=`top`;let t=Math.max(1,Math.floor((e.height-32)/18)),s=i.length,c=Math.max(0,s-t),l=i.slice(c);for(let e=0;e<l.length-1;e++){let t=l[e];t.startsWith(`[  `)?n.fillStyle=`#64748b`:t.startsWith(`root@`)?n.fillStyle=`#38bdf8`:t.includes(`command not found`)?n.fillStyle=`#f87171`:t.startsWith(`Ubuntu`)||t.startsWith(`Linux`)?n.fillStyle=`#34d399`:n.fillStyle=`#94a3b8`,n.fillText(t,16,16+e*18)}let u=l.length-1,d=l[u]||r;n.fillStyle=`#38bdf8`,n.fillText(d,16,16+u*18);let f=n.measureText(d).width;n.fillStyle=`#ffffff`,n.fillText(a,16+f,16+u*18);let p=n.measureText(a).width;o&&(n.fillStyle=`#34d399`,n.fillRect(16+f+p+2,16+u*18+2,8,14))}e._blinkInterval&&clearInterval(e._blinkInterval),n&&(e._blinkInterval=setInterval(()=>{o=!o,l()},500)),e.addEventListener(`click`,()=>{e.focus(),E(!0)}),e.addEventListener(`focus`,()=>E(!0)),e.addEventListener(`blur`,e=>{let t=document.getElementById(`vm-console-window`);(!t||!t.contains(e.relatedTarget))&&E(!1)}),e.focus(),e.addEventListener(`keydown`,e=>e.stopPropagation()),e.onkeydown=e=>{if(e.stopPropagation(),e.key===`Backspace`)e.preventDefault(),a=a.slice(0,-1),l();else if(e.key===`Enter`){e.preventDefault();let n=i[i.length-1]||r;i[i.length-1]=`${n}${a}`;let o=a.trim();if(o.length>0&&(s.push(o),c=-1),o!==``){if(o===`help`)i.push(`ZettNAS Virtual Machine Console v1.0 (QEMU/KVM Serial TTY)`),i.push(`Available guest commands: ls, cat, uname -a, ip a, df -h, free -h, uptime, whoami, id, pwd, ps, ping, date, echo, clear, help`);else if(o===`clear`)i=[];else if(o===`ls`||o===`dir`)i.push(`bin   dev  home  lib64  mnt  proc  run   srv  tmp  var`),i.push(`boot  etc  lib   media  opt  root  sbin  sys  usr`);else if(o===`ls -la`||o===`ls -l`||o===`ll`)i.push(`total 64`),i.push(`drwx------  4 root root 4096 Oct 12 19:30 .`),i.push(`drwxr-xr-x 19 root root 4096 Oct 12 19:25 ..`),i.push(`-rw-r--r--  1 root root 3106 Apr 22 14:15 .bashrc`),i.push(`-rw-r--r--  1 root root  161 Jul  9 09:12 .profile`),i.push(`drwx------  2 root root 4096 Oct 12 19:28 .ssh`);else if(o===`whoami`)i.push(`root`);else if(o===`id`)i.push(`uid=0(root) gid=0(root) groups=0(root)`);else if(o===`pwd`)i.push(`/root`);else if(o===`hostname`)i.push(t);else if(o.startsWith(`uname`))i.push(`Linux ${t} 6.8.0-45-generic #45-Ubuntu SMP PREEMPT_DYNAMIC x86_64 GNU/Linux`);else if(o===`uptime`)i.push(` 19:52:04 up 2 days, 4:18,  1 user,  load average: 0.08, 0.04, 0.01`);else if(o===`ip a`||o===`ip addr`||o===`ifconfig`)i.push(`1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000`),i.push(`    inet 127.0.0.1/8 scope host lo`),i.push(`2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000`),i.push(`    inet 192.168.1.180/24 metric 100 brd 192.168.1.255 scope global dynamic eth0`);else if(o.startsWith(`df`))i.push(`Filesystem      Size  Used Avail Use% Mounted on`),i.push(`/dev/vda1        62G  5.2G   54G   9% /`),i.push(`tmpfs            1.9G     0  1.9G   0% /dev/shm`),i.push(`efivarfs        128K   28K   96K  23% /sys/firmware/efi/efivars`);else if(o.startsWith(`free`))i.push(`               total        used        free      shared  buff/cache   available`),i.push(`Mem:           4.0Gi       482Mi       2.8Gi        12Mi       780Mi       3.4Gi`),i.push(`Swap:          2.0Gi          0B       2.0Gi`);else if(o.startsWith(`cat /etc/os-release`)||o.startsWith(`cat /etc/issue`))i.push(`PRETTY_NAME="Ubuntu 24.04.1 LTS"`),i.push(`NAME="Ubuntu"`),i.push(`VERSION_ID="24.04"`),i.push(`VERSION="24.04.1 LTS (Noble Numbat)"`),i.push(`ID=ubuntu`),i.push(`ID_LIKE=debian`),i.push(`HOME_URL="https://www.ubuntu.com/"`);else if(o.startsWith(`cat `)){let e=o.slice(4).trim();i.push(`cat: ${e}: No such file or directory`)}else if(o.startsWith(`ps`)||o===`top`)i.push(`  PID TTY          TIME CMD`),i.push(`    1 ?        00:00:02 systemd`),i.push(`  412 ?        00:00:00 systemd-journald`),i.push(`  890 ?        00:00:00 sshd`),i.push(` 1024 tty1     00:00:00 bash`),i.push(` 1045 tty1     00:00:00 ps`);else if(o.startsWith(`ping`)){let e=o.split(` `)[1]||`1.1.1.1`;i.push(`PING ${e} (${e}) 56(84) bytes of data.`),i.push(`64 bytes from ${e}: icmp_seq=1 ttl=58 time=11.4 ms`),i.push(`64 bytes from ${e}: icmp_seq=2 ttl=58 time=12.1 ms`),i.push(`--- ${e} ping statistics ---`),i.push(`2 packets transmitted, 2 received, 0% packet loss, time 1002ms`)}else o===`date`?i.push(new Date().toUTCString()):o.startsWith(`echo `)?i.push(o.slice(5)):o===`exit`||o===`logout`?(i.push(`logout`),i.push(`Ubuntu 24.04.1 LTS ${t} tty1`),i.push(`${t} login: root (automatic login)`)):i.push(`-bash: ${o.split(` `)[0]}: command not found`)}i.push(r),a=``,l()}else if(e.key===`Tab`)e.preventDefault(),a+=`    `,l();else if(e.key===`Escape`)e.preventDefault();else if(e.key===`ArrowUp`)e.preventDefault(),s.length>0&&c<s.length-1&&(c++,a=s[s.length-1-c],l());else if(e.key===`ArrowDown`)e.preventDefault(),c>0?(c--,a=s[s.length-1-c],l()):c===0&&(c=-1,a=``,l());else if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()===`c`){e.preventDefault();let t=i[i.length-1]||r;i[i.length-1]=`${t}${a}^C`,i.push(r),a=``,c=-1,l()}else(e.ctrlKey||e.metaKey)&&e.key.toLowerCase()===`l`?(e.preventDefault(),i=[r],l()):e.key===` `||e.code===`Space`?(e.preventDefault(),a+=` `,l()):e.key.length===1&&!e.ctrlKey&&!e.altKey&&!e.metaKey&&(e.preventDefault(),a+=e.key,l())},l()}typeof window<`u`&&!window._vmConsoleGlobalCaptureBound&&(window._vmConsoleGlobalCaptureBound=!0,window.addEventListener(`keydown`,e=>{let t=document.getElementById(`vm-console-window`);if(!t||t.style.display===`none`||t.classList.contains(`window-minimized`)||!(t.dataset.focused===`true`||t.contains(document.activeElement)))return;let n=document.activeElement?.tagName?.toLowerCase();if(!([`input`,`textarea`,`select`].includes(n)&&document.activeElement?.id!==`vm-console-hidden-input`)){if(e.key===`Tab`&&e.preventDefault(),(t._activeMode||`gui`)===`gui`){let n=t.querySelector(`.vnc-screen-target canvas`);if(n){if(document.activeElement===n)return;n.tabIndex=0;try{n.focus({preventScroll:!0})}catch{}if(O&&typeof O.focus==`function`)try{O.focus({preventScroll:!0})}catch{}F(e);return}let r=t.querySelector(`#vm-console-canvas`);r&&r.style.display!==`none`&&(document.activeElement!==r&&r.focus(),r.onkeydown&&e.target!==r&&r.onkeydown(e))}else{let n=t.querySelector(`#vm-cli-container`);if(n&&n.style.display!==`none`){document.activeElement!==n&&n.focus(),n.onkeydown&&e.target!==n&&n.onkeydown(e);return}let r=t.querySelector(`#vm-console-canvas`);r&&r.style.display!==`none`&&(document.activeElement!==r&&r.focus(),r.onkeydown&&e.target!==r&&r.onkeydown(e))}}},!0));var J=[{id:`ubuntu-2404`,name:`Ubuntu Server 24.04.1 LTS`,family:`linux`,badge:`Official Canonical`,edition:`Noble Numbat`,size_formatted:`2.6 GB`,arch:`x86_64`,kernel:`Linux 6.8`,url:`https://releases.ubuntu.com/24.04.1/ubuntu-24.04.1-live-server-amd64.iso`,filename:`ubuntu-24.04.1-live-server-amd64.iso`,desc:`Enterprise grade cloud & container host. Pre-configured with cloud-init and OpenSSH.`},{id:`debian-12`,name:`Debian 12.7.0 (Bookworm) Netinst`,family:`linux`,badge:`Stable Minimal`,edition:`Netinst Minimal`,size_formatted:`630 MB`,arch:`x86_64`,kernel:`Linux 6.1 LTS`,url:`https://cdimage.debian.org/cdimage/archive/12.7.0/amd64/iso-cd/debian-12.7.0-amd64-netinst.iso`,filename:`debian-12.7.0-amd64-netinst.iso`,desc:`The universal operating system. Ultra-light memory footprint, rock solid package ecosystem.`},{id:`alpine-320`,name:`Alpine Linux 3.20.3`,family:`linux`,badge:`Micro Hypervisor`,edition:`Standard Edition`,size_formatted:`209 MB`,arch:`x86_64`,kernel:`Linux 6.6 LTS`,url:`https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/x86_64/alpine-standard-3.20.3-x86_64.iso`,filename:`alpine-standard-3.20.3-x86_64.iso`,desc:`Musl libc and BusyBox based ultra-lean OS. Boots in 400ms, uses under 32MB host RAM.`},{id:`fedora-40`,name:`Fedora Server 40`,family:`linux`,badge:`Modern Enterprise`,edition:`Server Netinstall`,size_formatted:`2.5 GB`,arch:`x86_64`,kernel:`Linux 6.8`,url:`https://download.fedoraproject.org/pub/fedora/linux/releases/40/Server/x86_64/iso/Fedora-Server-dvd-x86_64-40-1.14.iso`,filename:`Fedora-Server-dvd-x86_64-40-1.14.iso`,desc:`Leading-edge Linux platform with native systemd-nspawn, Podman, and Cockpit integration.`},{id:`truenas-scale`,name:`TrueNAS SCALE 24.04.2`,family:`storage`,badge:`Scale-Out NAS`,edition:`Dragonfish`,size_formatted:`1.7 GB`,arch:`x86_64`,kernel:`Linux 6.6 LTS`,url:`https://download.sys.truenas.net/TrueNAS-SCALE-Dragonfish/24.04.2/TrueNAS-SCALE-24.04.2.iso`,filename:`TrueNAS-SCALE-24.04.2.iso`,desc:`Debian-based open hyper-converged scale-out storage, ZFS pools, and containerized apps.`},{id:`virtio-win`,name:`VirtIO Windows Guest Tools`,family:`windows`,badge:`KVM Drivers`,edition:`Stable 0.1.262`,size_formatted:`650 MB`,arch:`x86_64 / x86`,kernel:`WHQL Signed`,url:`https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso`,filename:`virtio-win-stable.iso`,desc:`Essential Red Hat signed VirtIO storage (viostor), network (NetKVM), and memory balloon drivers.`},{id:`win-server-2022`,name:`Windows Server 2022 Eval`,family:`windows`,badge:`Microsoft Eval`,edition:`Standard / Datacenter`,size_formatted:`4.7 GB`,arch:`x86_64`,kernel:`NT 10.0`,url:`https://software-download.microsoft.com/download/pr/SERVER_EVAL_x64FRE_en-us.iso`,filename:`Windows_Server_2022_Eval_x64.iso`,desc:`Official Microsoft 180-day evaluation image for Active Directory and Windows workloads.`}],Y={};async function X(e=`catalog`){let t=document.getElementById(`modal-iso-manager`);if(!t){t=document.createElement(`div`),t.id=`modal-iso-manager`,t.className=`os-window vm-iso-window`,t.style.cssText=`display: none; width: 860px; height: 620px; min-width: 600px; min-height: 440px;`;let e=Math.max(30,Math.floor((window.innerWidth-860)/2)+20),r=Math.max(40,Math.floor((window.innerHeight-620)/2)+25);t.style.left=`${e}px`,t.style.top=`${r}px`,t.innerHTML=`
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
    `,document.body.appendChild(t),window.DockManager&&window.DockManager.register(`vm-iso-manager`,t,`#i-vm`,`ISO Storage & Catalog`),s(t,t.querySelector(`#iso-win-header`)),t.addEventListener(`mousedown`,()=>l(t));let i=t.querySelector(`#iso-win-min`),a=t.querySelector(`#iso-win-max`),u=t.querySelector(`#iso-modal-close`);i&&(i.onclick=e=>{e&&(e.preventDefault(),e.stopPropagation()),t.classList.add(`window-minimized`),t.classList.remove(`open`),t.style.setProperty(`display`,`none`,`important`),window.DockManager&&window.DockManager.minimize(`vm-iso-manager`)});let d=!1,p=null;a&&(a.onclick=()=>{d?(p&&(t.style.left=p.left,t.style.top=p.top,t.style.width=p.width,t.style.height=p.height),d=!1):(p={left:t.style.left,top:t.style.top,width:t.style.width,height:t.style.height},t.style.left=`0px`,t.style.top=`36px`,t.style.width=`100vw`,t.style.height=`calc(100vh - 36px - 72px)`,d=!0)}),u&&(u.onclick=e=>{e&&(e.preventDefault(),e.stopPropagation()),t.classList.add(`window-minimized`),t.classList.remove(`open`),t.style.setProperty(`display`,`none`,`important`),window.DockManager&&window.DockManager.closeWindow(`vm-iso-manager`)});let m=t.querySelector(`#iso-dropzone`),h=t.querySelector(`#iso-file-input`),g=t.querySelector(`#btn-browse-iso`);g&&h&&(g.onclick=()=>h.click(),h.onchange=e=>{let t=e.target.files[0];t&&o(t)}),m&&(m.ondragover=e=>{e.preventDefault(),m.style.borderColor=`#38bdf8`,m.style.background=`rgba(14,165,233,0.1)`},m.ondragleave=()=>{m.style.borderColor=`rgba(14,165,233,0.4)`,m.style.background=`rgba(14,165,233,0.03)`},m.ondrop=e=>{e.preventDefault(),m.style.borderColor=`rgba(14,165,233,0.4)`,m.style.background=`rgba(14,165,233,0.03)`;let t=e.dataTransfer.files[0];t&&o(t)}),t.querySelector(`#btn-refresh-local-isos`)?.addEventListener(`click`,async()=>{await _(),c(),f(),n(`ISO list refreshed.`,`info`)})}function o(e){if(!e)return;let r=t.querySelector(`#iso-upload-progress-card`),i=t.querySelector(`#upload-progress-bar`),a=t.querySelector(`#upload-filename`),o=t.querySelector(`#upload-rate`);r&&(r.style.display=`block`),a&&(a.textContent=e.name),i&&(i.style.width=`0%`),o&&(o.textContent=`Starting upload...`);let s=new XMLHttpRequest,l=Date.now(),u=0;s.upload.onprogress=e=>{if(e.lengthComputable){let t=Math.round(e.loaded/e.total*100),n=Date.now(),r=(n-l)/1e3;if(r>=.25){let i=(e.loaded-u)/1048576/r;l=n,u=e.loaded,o&&(o.textContent=`${i.toFixed(1)} MB/s (${t}%)`)}i&&(i.style.width=`${t}%`)}},s.onload=async()=>{if(s.status>=200&&s.status<300)i&&(i.style.width=`100%`),o&&(o.textContent=`Upload Complete`),n(`ISO '${e.name}' uploaded successfully to /mnt/user/isos`,`success`),await _(),c(),f(),document.getElementById(`fm-refresh-btn`)?.click();else{let e=`Upload failed`;try{let t=JSON.parse(s.responseText);t&&t.detail&&(e=t.detail)}catch{}n(`Upload failed: ${e}`,`error`),o&&(o.textContent=`Error: ${e}`)}},s.onerror=()=>{n(`Network error while uploading ISO`,`error`),o&&(o.textContent=`Network Error`)},s.open(`POST`,`/api/vms/isos/upload`),s.setRequestHeader(`x-filename`,e.name),s.withCredentials=!0,s.send(e)}function c(){let e=t.querySelector(`#local-iso-list`);e&&(!m||m.length===0?e.innerHTML=`<div style="font-size: 11px; color: var(--muted); padding: 12px 0;">No local ISO images discovered in /mnt/user/isos.</div>`:(e.innerHTML=m.map(e=>`
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px;">
          <div style="display: flex; align-items: center; gap: 10px; min-width: 0; flex: 1;">
            <span style="font-size: 18px;">💿</span>
            <div style="min-width: 0; flex: 1;">
              <div style="font-size: 12.5px; font-weight: 700; color: #fff; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">${i(e.name)}</div>
              <div style="font-size: 10.5px; color: var(--muted); font-family: monospace;">${i(e.path)}</div>
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 8px; margin-left: 12px; flex-shrink: 0;">
            <span style="font-size: 11px; font-weight: 600; color: #94a3b8;">${e.size_formatted}</span>
            <button class="btn-pill-toggle btn-boot-iso" data-path="${i(e.path)}" style="padding: 4px 10px; font-size: 11px; font-weight: 700; background: rgba(14,165,233,0.18); color: #38bdf8; border-color: rgba(14,165,233,0.35);">▶ Boot VM</button>
            <button class="btn-pill-toggle btn-delete-iso" data-path="${i(e.path)}" data-name="${i(e.name)}" style="padding: 4px 8px; font-size: 11px; color: var(--crit, #ef4444); border-color: rgba(239,68,68,0.3);" title="Delete ISO from storage">🗑</button>
          </div>
        </div>
      `).join(``),e.querySelectorAll(`.btn-boot-iso`).forEach(e=>{e.onclick=()=>{let n=e.dataset.path;window.DockManager?window.DockManager.minimize(`vm-iso-manager`):t.style.display=`none`,w();let r=document.getElementById(`vm-create-iso`);r&&(r.value=n)}}),e.querySelectorAll(`.btn-delete-iso`).forEach(e=>{e.onclick=()=>{let t=e.dataset.path,i=e.dataset.name;u(r(`vms.delete_iso_title`,`Delete ISO Image`),`Are you sure you want to delete '${i}' from storage? This cannot be undone.`,async()=>{try{await a.delete(`/api/vms/isos?path=${encodeURIComponent(t)}`),n(`ISO '${i}' deleted successfully.`,`info`),await _(),c(),f(),document.getElementById(`fm-refresh-btn`)?.click()}catch(e){n(`Failed to delete ISO: ${e.message}`,`error`)}})}})))}function d(e,r){Y[e]&&clearInterval(Y[e]),Y[e]=setInterval(async()=>{try{let i=(await a.get(`/api/vms/catalog/tasks`)||[]).find(t=>t.catalog_id===e||t.task_id===r);if(!i)return;let o=t.querySelector(`#prog-wrap-${e}`),s=t.querySelector(`#prog-bar-${e}`),l=t.querySelector(`#prog-pct-${e}`),u=t.querySelector(`#prog-stat-${e}`),d=t.querySelector(`.btn-dl-catalog[data-id="${e}"]`);o&&(o.style.display=`block`),s&&(s.style.width=`${i.progress_pct||0}%`),l&&(l.textContent=`${i.progress_pct||0}%`),i.status===`downloading`?(u&&(u.textContent=`Downloading... ${i.speed_mb_s||0} MB/s (${i.progress_pct||0}%)`,u.style.color=`#38bdf8`),d&&(d.disabled=!0,d.textContent=`⏳ Downloading...`)):i.status===`completed`?(clearInterval(Y[e]),delete Y[e],s&&(s.style.width=`100%`),l&&(l.textContent=`100%`),u&&(u.textContent=`Downloaded to /mnt/user/isos`,u.style.color=`#34d399`),d&&(d.disabled=!1,d.textContent=`✓ Ready`,d.style.background=`rgba(16,185,129,0.2)`,d.style.borderColor=`#34d399`,d.style.color=`#34d399`),n(`Downloaded '${i.name||e}' to /mnt/user/isos`,`success`),await _(),f(),c(),document.getElementById(`fm-refresh-btn`)?.click()):(i.status===`failed`||i.status===`checksum_mismatch`)&&(clearInterval(Y[e]),delete Y[e],u&&(u.textContent=`Failed: ${i.error||`Verification error`}`,u.style.color=`#ef4444`),d&&(d.disabled=!1,d.textContent=`⬇ Retry`,d.style.opacity=`1`),n(`Download failed: ${i.error||`Error`}`,`error`))}catch{}},800)}function f(e){let r=t.querySelector(`#catalog-grid-container`);r&&(r.innerHTML=(e||J).map(e=>{let t=(m||[]).some(t=>t.name.toLowerCase()===e.filename.toLowerCase()||t.path&&t.path.toLowerCase().endsWith(e.filename.toLowerCase()));return`
        <div class="catalog-card glassmorphic-card" style="padding: 14px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.08); background: rgba(18,26,38,0.6);">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6px;">
            <div>
              <span style="font-size: 9px; font-weight: 800; padding: 2px 6px; border-radius: 4px; background: rgba(14,165,233,0.15); color: #38bdf8;">${e.badge}</span>
              ${t?`<span style="font-size: 9px; font-weight: 800; padding: 2px 6px; border-radius: 4px; background: rgba(16,185,129,0.2); color: #34d399; margin-left: 6px;">✓ In Storage</span>`:``}
              <div style="font-weight: 700; color: #fff; font-size: 13px; margin-top: 4px;">${i(e.name)}</div>
            </div>
            <span style="font-size: 11px; font-weight: 700; color: #94a3b8;">${e.size_formatted}</span>
          </div>
          <div style="font-size: 10px; color: var(--muted); margin: 6px 0 12px 0; line-height: 1.4;">${i(e.desc||e.description||``)}</div>
          
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
      `}).join(``),r.querySelectorAll(`.btn-dl-catalog:not(:disabled)`).forEach(e=>{e.onclick=async()=>{let r=e.dataset.id;e.disabled=!0,e.textContent=`⏳ Connecting...`;let i=t.querySelector(`#prog-wrap-${r}`),o=t.querySelector(`#prog-stat-${r}`);i&&(i.style.display=`block`),o&&(o.textContent=`Contacting download mirror...`,o.style.color=`#38bdf8`);try{let e=await a.post(`/api/vms/catalog/${r}/download`);if(e&&e.status===`already_present`){n(`ISO already exists in /mnt/user/isos`,`info`),await _(),f(),c();return}d(r,e.task_id)}catch(t){n(`Failed to initiate download: ${t.message}`,`error`),o&&(o.textContent=`Error: ${t.message}`,o.style.color=`#ef4444`),e.disabled=!1,e.textContent=`⬇ Retry`}}}),r.querySelectorAll(`.btn-boot-catalog-iso`).forEach(e=>{e.onclick=()=>{let n=e.dataset.filename,r=(m||[]).find(e=>e.name.toLowerCase()===n.toLowerCase()),i=r?r.path:`/mnt/user/isos/${n}`;window.DockManager?window.DockManager.minimize(`vm-iso-manager`):t.style.display=`none`,w();let a=document.getElementById(`vm-create-iso`);a&&(a.value=i)}}))}let p=t.querySelector(`#tab-btn-catalog`),h=t.querySelector(`#tab-btn-local`),g=t.querySelector(`#tab-content-catalog`),v=t.querySelector(`#tab-content-local`);function y(e){e===`local`?(h?.classList.add(`active`),p?.classList.remove(`active`),v&&(v.style.display=`block`),g&&(g.style.display=`none`)):(p?.classList.add(`active`),h?.classList.remove(`active`),g&&(g.style.display=`block`),v&&(v.style.display=`none`))}p&&(p.onclick=()=>y(`catalog`)),h&&(h.onclick=()=>y(`local`)),y(e),window.DockManager?window.DockManager.restore(`vm-iso-manager`):t.style.display=`flex`,l(t),c(),f();try{let[e,t]=await Promise.all([a.get(`/api/vms/catalog`).catch(()=>null),a.get(`/api/vms/catalog/tasks`).catch(()=>null)]);e&&e.length>0&&f(e),t&&t.length>0&&t.forEach(e=>{e.status===`downloading`&&d(e.catalog_id,e.task_id)})}catch{}}typeof window<`u`&&(window.openVmConnectModal=S,window.openVmEditModal=x);export{K as C,E as D,V as E,L as O,G as S,x as T,_,F as a,b,N as c,z as d,T as f,g,R as h,I as i,M as l,H as m,O as n,A as o,P as p,k as r,B as s,J as t,j as u,X as v,w,S as x,C as y};