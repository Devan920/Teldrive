// frontend/app.js

// Utility to format bytes
function formatBytes(bytes) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (bytes >= 1024 && i < units.length - 1) {
    bytes /= 1024;
    i++;
  }
  return `${bytes.toFixed(1)} ${units[i]}`;
}

// Load file list
async function loadFiles(query = "") {
  const resp = await fetch(`/api/files?search=${encodeURIComponent(query)}`);
  if (!resp.ok) return alert("Failed to load files");
  const files = await resp.json();
  const tbody = document.getElementById("fileTableBody");
  tbody.innerHTML = "";
  files.forEach(f => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="p-2 border-b">${f.filename}</td>
      <td class="p-2 border-b">${formatBytes(f.file_size)}</td>
      <td class="p-2 border-b">${new Date(f.created_at).toLocaleString()}</td>
      <td class="p-2 border-b text-center space-x-2">
        <a href="/api/download/${f.id}" class="text-blue-400 hover:underline">Download</a>
        <button data-id="${f.id}" class="deleteBtn text-red-400 hover:underline">Delete</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
  attachDeleteHandlers();
}

function attachDeleteHandlers() {
  document.querySelectorAll('.deleteBtn').forEach(btn => {
    btn.onclick = async () => {
      const id = btn.dataset.id;
      const resp = await fetch(`/api/delete/${id}`, { method: "DELETE" });
      if (resp.ok) loadFiles(document.getElementById('searchInput').value);
      else alert('Delete failed');
    };
  });
}

// Upload handling
const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('fileInput');
const progressContainer = document.getElementById('progressContainer');

function createProgressBar(fileName) {
  const container = document.createElement('div');
  container.className = 'mb-2';
  container.innerHTML = `
    <span class="block mb-1">${fileName}</span>
    <div class="w-full bg-gray-700 rounded"><div class="bg-blue-600 h-2 w-0" data-bar></div></div>
  `;
  progressContainer.appendChild(container);
  return container.querySelector('[data-bar]');
}

async function uploadFiles(files) {
  const formData = new FormData();
  for (const file of files) {
    formData.append('files', file);
  }
  // Simple fetch without progress (browser doesn't expose upload progress via fetch yet)
  const resp = await fetch('/api/upload', { method: 'POST', body: formData });
  if (!resp.ok) return alert('Upload failed');
  const result = await resp.json();
  console.log(result);
  // Reset progress UI
  progressContainer.innerHTML = '';
  loadFiles();
}

dropzone.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', e => uploadFiles(e.target.files));

dropzone.addEventListener('dragover', e => { e.preventDefault(); dropzone.classList.add('bg-gray-800'); });
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('bg-gray-800'));
dropzone.addEventListener('drop', e => {
  e.preventDefault();
  dropzone.classList.remove('bg-gray-800');
  uploadFiles(e.dataTransfer.files);
});

// Search handling
const searchBtn = document.getElementById('searchBtn');
searchBtn.onclick = () => loadFiles(document.getElementById('searchInput').value);

// Initial load
loadFiles();
