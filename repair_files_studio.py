from pathlib import Path
from datetime import datetime

html = Path("dashboard_v2/index.html")
source = html.read_text()

start_marker = "// PYFORGE_FILES_WORKSPACE_V1"
new_marker = "// PYFORGE_FILES_STUDIO_V2"
console_marker = "// PYFORGE_CONSOLE_UI_V3"

if start_marker not in source:
    raise SystemExit("STOP: Old Files script marker not found.")

if console_marker not in source:
    raise SystemExit("STOP: Console marker not found.")

if new_marker in source:
    raise SystemExit("STOP: New Files Studio script already exists.")

start = source.index(start_marker)
end = source.index("</script>", start)
close = source.rfind("})();", start, end)

if close == -1:
    raise SystemExit("STOP: Could not identify the end of the old Files script.")

close += len("})();")

backup = Path(
    "backups/checkpoints/index-before-files-repair-"
    + datetime.now().strftime("%Y%m%d-%H%M%S")
    + ".html"
)
backup.parent.mkdir(parents=True, exist_ok=True)
backup.write_text(source)

js = r'''// PYFORGE_FILES_STUDIO_V2
(() => {
  const API = "http://127.0.0.1:8001";
  const $ = id => document.getElementById(id);

  const picker = $("files-project-picker");
  const workspace = $("files-workspace");
  const projectList = $("files-project-list");
  const projectCount = $("files-project-count");
  const projectLabel = $("files-project-name");
  const status = $("files-status");
  const pathLabel = $("files-path");
  const fileList = $("files-list");
  const editor = $("files-editor");
  const editorTitle = $("files-editor-title");
  const lineNumbers = $("files-line-numbers");
  const editorState = $("files-editor-state");

  if (!picker || !workspace || !editor || !lineNumbers) {
    console.error("Files Studio: required HTML elements are missing.");
    return;
  }

  let project = "";
  let directory = "";
  let currentFile = "";
  let dirty = false;

  const enc = encodeURIComponent;

  const escapeHTML = value => String(value).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;",
    '"': "&quot;", "'": "&#39;"
  })[c]);

  function message(value, error = false) {
    status.textContent = value;
    status.style.color = error ? "#ff7777" : "#79e6ae";
  }

  async function request(url, options = {}) {
    const response = await fetch(API + url, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {})
      }
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      const detail = typeof data.detail === "string"
        ? data.detail : JSON.stringify(data.detail || data);
      throw new Error(detail || `Request failed (${response.status})`);
    }
    return data;
  }

  function canLeaveEditor() {
    return !dirty || confirm(
      "You have unsaved changes. Leave without saving?"
    );
  }

  function updateLineNumbers() {
    const count = Math.max(1, editor.value.split("\n").length);
    lineNumbers.textContent = Array.from(
      {length: count}, (_, i) => i + 1
    ).join("\n");

    lineNumbers.scrollTop = editor.scrollTop;

    if (editorState) {
      editorState.textContent = dirty
        ? "● Unsaved changes"
        : currentFile ? "✓ Saved" : "No file open";
      editorState.style.color = dirty ? "#ffd36a" : "#8bb4d4";
    }
  }

  function clearEditor() {
    currentFile = "";
    dirty = false;
    editor.value = "";
    editor.disabled = true;
    editorTitle.textContent = "File Editor";
    updateLineNumbers();
  }

  async function loadProjects() {
    projectCount.textContent = "Loading projects...";
    projectList.textContent = "Connecting to PyForge...";

    try {
      const data = await request("/api/projects");
      projectCount.textContent = `${data.count} project(s) available`;

      if (!data.projects || !data.projects.length) {
        projectList.textContent =
          "No projects found. Create one from the Projects page first.";
        return;
      }

      projectList.innerHTML = data.projects.map(item => `
        <div style="display:flex;gap:12px;align-items:center;
          justify-content:space-between;flex-wrap:wrap;padding:14px;
          border:1px solid #42617a;border-radius:10px;background:#10243a">
          <div style="min-width:0">
            <strong>${escapeHTML(item.name)}</strong>
            <div style="font-size:12px;opacity:.7;margin-top:4px">
              ${escapeHTML(item.type || "Project")}
            </div>
          </div>
          <button type="button"
            data-open-project="${escapeHTML(item.name)}">
            Open Workspace →
          </button>
        </div>
      `).join("");
    } catch (error) {
      projectCount.textContent = "Backend connection problem";
      projectList.textContent = "Could not load projects.";
      console.error(error);
    }
  }

  async function loadDirectory(nextDirectory = "", skipGuard = false) {
    if (!project) return;
    if (!skipGuard && !canLeaveEditor()) return;

    clearEditor();
    directory = nextDirectory;
    pathLabel.textContent = "/" + (directory || "");
    fileList.textContent = "Loading files...";

    try {
      const data = await request(
        `/api/projects/${enc(project)}/files?directory=${enc(directory)}`
      );

      if (!data.entries.length) {
        fileList.textContent = "This folder is empty.";
        message("Folder loaded successfully.");
        return;
      }

      fileList.innerHTML = data.entries.map(entry => {
        const folder = entry.type === "folder";
        const path = escapeHTML(entry.path);
        const name = escapeHTML(entry.name);

        return `
          <div class="files-entry">
            <button type="button" class="files-entry-open"
              data-kind="${folder ? "folder" : "file"}"
              data-path="${path}">
              <span class="files-entry-name">
                ${folder ? "📁" : "📄"} ${name}
              </span>
              <span style="display:block;font-size:11px;opacity:.65">
                ${folder ? "Folder" : "File"}
              </span>
            </button>
            <div class="files-menu">
              <button type="button" class="files-menu-toggle"
                aria-label="Actions for ${name}"
                aria-expanded="false">⋮</button>
              <div class="files-menu-panel">
                ${folder ? "" : `<button data-action="edit" data-path="${path}">✏️ Edit</button>`}
                ${folder ? "" : `<button data-action="copy" data-path="${path}">📋 Copy contents</button>`}
                ${folder ? "" : `<button data-action="duplicate" data-path="${path}">▣ Duplicate</button>`}
                <button data-action="copy-path" data-path="${path}">🔗 Copy path</button>
                <button data-action="rename" data-path="${path}">✏️ Rename</button>
                ${folder ? "" : `<button data-action="download" data-path="${path}">↓ Download</button>`}
                <button class="files-delete-action"
                  data-action="delete" data-kind="${folder ? "folder" : "file"}"
                  data-path="${path}">🗑 Delete</button>
              </div>
            </div>
          </div>`;
      }).join("");

      message(`${data.entries.length} item(s) loaded.`);
    } catch (error) {
      fileList.textContent = "Could not load this folder.";
      message(error.message, true);
    }
  }

  async function openFile(path) {
    if (!canLeaveEditor()) return;

    try {
      const data = await request(
        `/api/projects/${enc(project)}/file?path=${enc(path)}`
      );

      currentFile = path;
      editor.value = data.content;
      editor.disabled = false;
      dirty = false;
      editorTitle.textContent = path;
      updateLineNumbers();
      message("File opened.");
      editor.focus();
    } catch (error) {
      message("Could not open file: " + error.message, true);
    }
  }

  async function saveFile() {
    if (!project || !currentFile) {
      message("Open a file before saving.", true);
      return;
    }

    try {
      const result = await request(
        `/api/projects/${enc(project)}/file`,
        {
          method: "PUT",
          body: JSON.stringify({
            path: currentFile,
            content: editor.value
          })
        }
      );

      dirty = false;
      updateLineNumbers();
      message(result.message || "File saved.");
    } catch (error) {
      message("Save failed: " + error.message, true);
    }
  }

  async function createFolder() {
    if (!project) return message("Open a project first.", true);
    if (!canLeaveEditor()) return;

    const name = prompt("Enter the new folder name:");
    if (name === null) return;
    if (!name.trim()) return message("Folder name cannot be empty.", true);

    const path = directory
      ? `${directory}/${name.trim()}` : name.trim();

    try {
      await request(`/api/projects/${enc(project)}/folder`, {
        method: "POST",
        body: JSON.stringify({path})
      });
      message("Folder created.");
      await loadDirectory(directory, true);
    } catch (error) {
      message("Folder creation failed: " + error.message, true);
    }
  }

  async function createFile() {
    if (!project) return message("Open a project first.", true);
    if (!canLeaveEditor()) return;

    const name = prompt("Enter a filename, including its extension:");
    if (name === null) return;
    if (!name.trim()) return message("Filename cannot be empty.", true);

    const path = directory
      ? `${directory}/${name.trim()}` : name.trim();

    try {
      await request(`/api/projects/${enc(project)}/file`, {
        method: "POST",
        body: JSON.stringify({path, content: ""})
      });
      message("File created.");
      await loadDirectory(directory, true);
      await openFile(path);
    } catch (error) {
      message("File creation failed: " + error.message, true);
    }
  }

  async function handleItemAction(action, path, kind) {
    if (["rename", "duplicate", "delete"].includes(action)) {
      if (!canLeaveEditor()) return;
    }

    try {
      if (action === "edit") {
        await openFile(path);
        return;
      }

      if (action === "copy") {
        const data = await request(
          `/api/projects/${enc(project)}/file?path=${enc(path)}`
        );
        try {
          await navigator.clipboard.writeText(data.content);
          message("File contents copied.");
        } catch (_) {
          prompt("Copy the file contents:", data.content);
        }
        return;
      }

      if (action === "copy-path") {
        const value = `projects/${project}/${path}`;
        try {
          await navigator.clipboard.writeText(value);
          message("Path copied: " + value);
        } catch (_) {
          prompt("Copy this path:", value);
        }
        return;
      }

      if (action === "download") {
        const link = document.createElement("a");
        link.href = `${API}/api/projects/${enc(project)}/download?path=${enc(path)}`;
        link.download = path.split("/").pop();
        document.body.appendChild(link);
        link.click();
        link.remove();
        message("Download requested.");
        return;
      }

      if (action === "rename") {
        const oldName = path.split("/").pop();
        const newName = prompt("Enter the new name:", oldName);
        if (newName === null || !newName.trim()) return;

        await request(`/api/projects/${enc(project)}/item/rename`, {
          method: "POST",
          body: JSON.stringify({path, new_name: newName.trim()})
        });

        if (currentFile === path) clearEditor();
        message("Item renamed.");
        await loadDirectory(directory, true);
        return;
      }

      if (action === "duplicate") {
        const oldName = path.split("/").pop();
        const dot = oldName.lastIndexOf(".");
        const suggested = dot > 0
          ? oldName.slice(0, dot) + "_copy" + oldName.slice(dot)
          : oldName + "_copy";

        const newName = prompt("Name for the duplicate:", suggested);
        if (newName === null || !newName.trim()) return;

        await request(`/api/projects/${enc(project)}/item/duplicate`, {
          method: "POST",
          body: JSON.stringify({path, new_name: newName.trim()})
        });

        message("File duplicated.");
        await loadDirectory(directory, true);
        return;
      }

      if (action === "delete") {
        const itemName = path.split("/").pop();
        const warning = kind === "folder"
          ? `Delete folder "${itemName}" and everything inside it? This cannot be undone.`
          : `Delete file "${itemName}"? This cannot be undone.`;

        if (!confirm(warning)) return;

        await request(`/api/projects/${enc(project)}/item`, {
          method: "DELETE",
          body: JSON.stringify({path})
        });

        if (currentFile === path || currentFile.startsWith(path + "/")) {
          clearEditor();
        }

        message("Item deleted.");
        await loadDirectory(directory, true);
      }
    } catch (error) {
      message("Action failed: " + error.message, true);
    }
  }

  function selectProject(name) {
    if (!canLeaveEditor()) return;

    project = name;
    directory = "";
    clearEditor();
    picker.hidden = true;
    workspace.hidden = false;
    projectLabel.textContent = name;
    loadDirectory("", true);
  }

  $("files-project-refresh").addEventListener("click", loadProjects);

  projectList.addEventListener("click", event => {
    const button = event.target.closest("[data-open-project]");
    if (button) selectProject(button.dataset.openProject);
  });

  $("files-back-projects").addEventListener("click", () => {
    if (!canLeaveEditor()) return;
    project = "";
    directory = "";
    clearEditor();
    workspace.hidden = true;
    picker.hidden = false;
    loadProjects();
  });

  $("files-refresh").addEventListener("click", () => loadDirectory(directory));

  $("files-up").addEventListener("click", () => {
    if (!directory) return message("Already at the project root.");
    const parts = directory.split("/");
    parts.pop();
    loadDirectory(parts.join("/"));
  });

  $("files-new-folder").addEventListener("click", createFolder);
  $("files-new-file").addEventListener("click", createFile);
  $("files-save").addEventListener("click", saveFile);

  $("files-download-zip").addEventListener("click", () => {
    if (!project) return;
    const link = document.createElement("a");
    link.href = `${API}/api/projects/${enc(project)}/download-zip`;
    link.download = `${project}.zip`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    message("Project ZIP download requested.");
  });

  $("files-close-editor").addEventListener("click", () => {
    if (!canLeaveEditor()) return;
    clearEditor();
    message("Editor closed.");
  });

  editor.addEventListener("input", () => {
    dirty = true;
    updateLineNumbers();
    message("Unsaved changes.");
  });

  editor.addEventListener("scroll", () => {
    lineNumbers.scrollTop = editor.scrollTop;
  });

  fileList.addEventListener("click", event => {
    const toggle = event.target.closest(".files-menu-toggle");

    if (toggle) {
      const panel = toggle.parentElement.querySelector(".files-menu-panel");
      const opening = !panel.classList.contains("open");

      document.querySelectorAll("#page-files .files-menu-panel.open")
        .forEach(item => item.classList.remove("open"));

      if (opening) {
        panel.classList.add("open");
        toggle.setAttribute("aria-expanded", "true");
      } else {
        toggle.setAttribute("aria-expanded", "false");
      }
      return;
    }

    const actionButton = event.target.closest("button[data-action]");
    if (actionButton) {
      handleItemAction(
        actionButton.dataset.action,
        actionButton.dataset.path,
        actionButton.dataset.kind
      );
      actionButton.closest(".files-menu-panel").classList.remove("open");
      return;
    }

    const openButton = event.target.closest("button[data-kind]");
    if (!openButton) return;

    const path = openButton.dataset.path;
    if (openButton.dataset.kind === "folder") {
      loadDirectory(path);
    } else {
      openFile(path);
    }
  });

  document.addEventListener("click", event => {
    if (!event.target.closest("#page-files .files-menu")) {
      document.querySelectorAll("#page-files .files-menu-panel.open")
        .forEach(item => item.classList.remove("open"));
    }
  });

  document.querySelectorAll('[data-page="files"]').forEach(button => {
    button.addEventListener("click", () => {
      if (project) loadDirectory(directory);
      else loadProjects();
    });
  });

  window.addEventListener("pyforge-project-opened", event => {
    if (event.detail && event.detail.name) {
      selectProject(event.detail.name);
    }
  });

  window.addEventListener("beforeunload", event => {
    if (dirty) {
      event.preventDefault();
      event.returnValue = "";
    }
  });

  if (window.PYFORGE_SELECTED_PROJECT) {
    selectProject(window.PYFORGE_SELECTED_PROJECT);
  } else {
    loadProjects();
  }
})();'''

updated = source[:start] + js + source[close:]

if updated.count(new_marker) != 1:
    raise SystemExit("STOP: New Files marker verification failed.")

if updated.count(console_marker) != 1:
    raise SystemExit("STOP: Console marker verification failed.")

if start_marker in updated:
    raise SystemExit("STOP: Old Files marker still exists.")

if updated.count("</script>") != source.count("</script>"):
    raise SystemExit("STOP: Script tag count changed.")

html.write_text(updated)

print("FILES STUDIO JAVASCRIPT REPLACED")
print("Backup:", backup)
print("New Files marker:", updated.count(new_marker))
print("Old Files marker:", updated.count(start_marker))
print("Console marker:", updated.count(console_marker))
print("Script tag count preserved:", updated.count("</script>"))
