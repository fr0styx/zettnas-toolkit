import { ZettEventBus } from './event-bus.js';
import { showToast } from './toast.js';
import { api } from './api.js';
import { DockManager, bringToFront } from './components/dock.js';

window.addEventListener('DOMContentLoaded', () => {
    const $ = (id) => document.getElementById(id);
  // Folder Browser Modal Logic
  const btnBrowseDst = $("btn-browse-dst");
  const btnCopyDst = $("btn-copy-dst");
  const fbModal = $("folder-browser-modal");
  const fbCurrentPath = $("fb-current-path");
  const fbList = $("fb-list");
  const fbCancel = $("fb-cancel");
  const fbClose = $("fb-close");
  const fbSelect = $("fb-select");
  const fbCreateFolderBtn = $("fb-create-folder");
  const fbNewFolderName = $("fb-new-folder-name");

  let currentBrowsePath = "/mnt/user/";
  let currentBrowseDirs = [];
  let browseRoots = ["/mnt/user"];

  // Only paths inside an allowed root (enforced server-side) are navigable.
  const isWithinRoots = (p) => {
    const norm = p.replace(/\/+$/, "") || "/";
    return browseRoots.some(r => {
      const root = r.replace(/\/+$/, "") || "/";
      return norm === root || norm.startsWith(root + "/");
    });
  };
  let fbSortReverse = false;

  const fbSearchBar = $("fb-search-bar");
  const fbSortBtn = $("fb-sort-btn");

  if (fbSearchBar) fbSearchBar.addEventListener("input", renderBrowseList);
  if (fbSortBtn) {
    fbSortBtn.addEventListener("click", () => {
      fbSortReverse = !fbSortReverse;
      fbSortBtn.textContent = fbSortReverse ? "Z-A" : "A-Z";
      renderBrowseList();
    });
  }

  function renderBrowseBreadcrumbs(fullPath) {
    if (!fbCurrentPath) return;
    fbCurrentPath.innerHTML = "";
    const parts = fullPath.split("/").filter(p => p.length > 0);
    let builtPath = "/";
    
    const rootLink = document.createElement("span");
    rootLink.textContent = "/";
    rootLink.style.padding = "2px 4px";
    rootLink.style.borderRadius = "4px";
    rootLink.style.color = "var(--muted)";
    fbCurrentPath.appendChild(rootLink);

    parts.forEach((part, i) => {
      builtPath += part + "/";
      const p = builtPath;
      const span = document.createElement("span");
      span.textContent = part;
      span.style.padding = "2px 4px";
      span.style.borderRadius = "4px";
      if (isWithinRoots(p)) {
        span.style.cursor = "pointer";
        span.onmouseover = () => span.style.background = "rgba(255,255,255,0.1)";
        span.onmouseout = () => span.style.background = "transparent";
        span.onclick = () => loadBrowsePath(p);
      } else {
        span.style.color = "var(--muted)";
      }
      
      fbCurrentPath.appendChild(span);
      
      if (i < parts.length - 1) {
        const sep = document.createElement("span");
        sep.textContent = "/";
        sep.style.color = "var(--muted)";
        fbCurrentPath.appendChild(sep);
      }
    });
  }

  function renderBrowseList() {
    if (!fbList) return;
    fbList.innerHTML = "";
    const filterText = (fbSearchBar ? fbSearchBar.value.toLowerCase() : "");
    let upDir = currentBrowseDirs.find(d => d.name === "..");
    let otherDirs = currentBrowseDirs.filter(d => d.name !== "..");
    
    if (filterText) {
      otherDirs = otherDirs.filter(d => d.name.toLowerCase().includes(filterText));
    }
    if (fbSortReverse) {
      otherDirs.reverse();
    }
    
    let displayDirs = [];
    if (upDir && !filterText) displayDirs.push(upDir);
    displayDirs = displayDirs.concat(otherDirs);

    if (displayDirs.length === 0) {
      fbList.innerHTML = `<div style="padding: 10px 14px; color: var(--muted); font-size: 11px;">No folders found.</div>`;
      return;
    }

    displayDirs.forEach(d => {
      const div = document.createElement("div");
      div.style.padding = "10px 14px";
      div.style.borderBottom = "1px solid rgba(255,255,255,0.05)";
      div.style.cursor = "pointer";
      div.style.display = "flex";
      div.style.alignItems = "center";
      div.style.gap = "10px";
      div.onmouseover = () => div.style.background = "rgba(255,255,255,0.03)";
      div.onmouseout = () => div.style.background = "transparent";
      
      const icon = document.createElement("span");
      icon.textContent = d.name === ".." ? "⤴️" : "📁";
      icon.style.fontSize = "14px";
      icon.style.opacity = d.name === ".." ? "0.6" : "1";
      
      const text = document.createElement("span");
      text.textContent = d.name;
      text.style.fontSize = "12px";
      text.style.color = d.name === ".." ? "var(--muted)" : "#fff";
      
      div.appendChild(icon);
      div.appendChild(text);
      
      div.addEventListener("click", () => {
        if (fbSearchBar) fbSearchBar.value = "";
        loadBrowsePath(d.path);
      });
      fbList.appendChild(div);
    });
  }

  async function loadBrowsePath(targetPath, isFallback = false) {
    try {
      const res = await api.request(`/api/browse?path=${encodeURIComponent(targetPath || "")}`);
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data.roots) && data.roots.length) browseRoots = data.roots;
        currentBrowsePath = data.current;
        currentBrowseDirs = data.dirs;
        renderBrowseBreadcrumbs(currentBrowsePath);
        renderBrowseList();
      } else if (!isFallback) {
        // Path missing or outside the allowed folders: fall back to the default root.
        loadBrowsePath("", true);
      } else {
        const err = await res.json().catch(() => ({}));
        showToast("Failed to load folder: " + (err.detail || res.status), "error");
      }
    } catch (e) {
      if (typeof showToast === "function") showToast("Failed to load folder: " + e, "error");
      else console.error(e);
    }
  }

  function closeFbModal() {
    if (DockManager) DockManager.unregister("fb");
    if (fbModal) fbModal.classList.remove("open");
  }

  if (btnBrowseDst) {
    btnBrowseDst.addEventListener("click", (e) => {
      e.preventDefault();
      const currentDst = (btnCopyDst && btnCopyDst.value) ? btnCopyDst.value : "/mnt/user/";
      loadBrowsePath(currentDst || "/mnt/user/");
      if (fbModal) {
        fbModal.classList.add("open");
        if (DockManager) DockManager.register("fb", fbModal, "#i-storage", "Folder Browser");
        if (bringToFront) bringToFront(fbModal.querySelector(".smart-modal-window"));
      }
    });
  }

  if (fbCancel) fbCancel.addEventListener("click", closeFbModal);
  if (fbClose) fbClose.addEventListener("click", closeFbModal);
  if (fbModal) {
    fbModal.addEventListener("click", (e) => {
      if (e.target === fbModal) closeFbModal();
    });
  }
  const minBtn = document.getElementById("fb-min");
  if (minBtn) minBtn.addEventListener("click", () => { if (DockManager) DockManager.minimize("fb"); });

  if (fbSelect) {
    fbSelect.addEventListener("click", () => {
      if (btnCopyDst) {
        btnCopyDst.value = currentBrowsePath;
      }
      closeFbModal();
      ZettEventBus.dispatchEvent(new CustomEvent('folder_selected', { detail: currentBrowsePath }));
      
      const btnCopySave = $("btn-copy-save");
      if (btnCopySave) {
        btnCopySave.textContent = "Saved!";
        setTimeout(() => { btnCopySave.textContent = "💾 Save Configuration"; }, 2000);
      }
    });
  }

  if (fbCreateFolderBtn && fbNewFolderName) {
    fbCreateFolderBtn.addEventListener("click", async () => {
      const folderName = fbNewFolderName.value.trim();
      if (!folderName) return;
      if (folderName.includes("/") || folderName.includes("..")) return;
      
      const newPath = currentBrowsePath + (currentBrowsePath.endsWith("/") ? "" : "/") + folderName;
      try {
        fbCreateFolderBtn.textContent = "...";
        const res = await api.request("/api/mkdir", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: { path: newPath }
        });
        if (res.ok) {
          fbNewFolderName.value = "";
          fbNewFolderName.placeholder = "New folder name...";
          loadBrowsePath(currentBrowsePath); // Reload current path to show the new folder in the list
        } else {
          const errData = await res.json().catch(() => ({}));
          fbNewFolderName.value = "";
          fbNewFolderName.placeholder = "Error: " + (errData.detail || errData.error || "Failed");
        }
      } catch(e) {
        fbNewFolderName.value = "";
        fbNewFolderName.placeholder = "Network Error";
      } finally {
        fbCreateFolderBtn.textContent = "+ Create";
      }
    });
    
    // allow enter key
    fbNewFolderName.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        fbCreateFolderBtn.click();
      }
    });
  }

});
