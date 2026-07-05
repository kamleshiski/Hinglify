const BACKEND_URL = 'https://hinglify-backend.onrender.com';

/**
 * Hinglish Subtitle Converter — Frontend Logic
 *
 * Handles file upload (drag-and-drop + click), conversion API calls,
 * progress updates, preview rendering, and download.
 */

// ─── DOM Elements ────────────────────────────────────────────────────────────

const uploadZone = document.getElementById('uploadZone');
const fileInput = document.getElementById('fileInput');
const uploadPrompt = document.getElementById('uploadPrompt');
const fileCard = document.getElementById('fileCard');
const fileName = document.getElementById('fileName');
const fileSize = document.getElementById('fileSize');
const removeFileBtn = document.getElementById('removeFile');
const uploadError = document.getElementById('uploadError');
const uploadErrorText = document.getElementById('uploadErrorText');
const uploadSection = document.getElementById('uploadSection');

const convertBtn = document.getElementById('convertBtn');
const convertLabel = document.getElementById('convertLabel');
const convertSpinner = document.getElementById('convertSpinner');

const progressSection = document.getElementById('progressSection');
const progressBar = document.getElementById('progressBar');
const progressText = document.getElementById('progressText');
const progressNotice = document.getElementById('progressNotice');

const resultSection = document.getElementById('resultSection');
const successBannerText = document.getElementById('successBannerText');
const previewRows = document.getElementById('previewRows');
const unconvertedNotice = document.getElementById('unconvertedNotice');
const downloadBtn = document.getElementById('downloadBtn');
const resetLink = document.getElementById('resetLink');

const errorInline = document.getElementById('errorInline');
const errorText = document.getElementById('errorText');
const errorClose = document.getElementById('errorClose');


// ─── Constants ───────────────────────────────────────────────────────────────

const MAX_FILE_SIZE = 5 * 1024 * 1024; // 5MB


// ─── State ───────────────────────────────────────────────────────────────────

let selectedFile = null;
let convertedSrtContent = null;
let originalFilename = null;
let isConverting = false;


// ─── Initialization ──────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  setupUploadZone();
  setupEventListeners();
  setupNavbarScroll();

  // Wake up backend on page load (Render free tier spins down after inactivity)
  fetch(`${BACKEND_URL}/health`, { method: 'GET' })
    .catch(() => {}); // silent — user never sees this
});


// ─── Navbar Backdrop Blur on Scroll ──────────────────────────────────────────

function setupNavbarScroll() {
  const navbar = document.getElementById('navbar');
  window.addEventListener('scroll', () => {
    if (window.scrollY > 20) {
      navbar.classList.add('scrolled');
    } else {
      navbar.classList.remove('scrolled');
    }
  });
}


// ─── File Upload ─────────────────────────────────────────────────────────────

function setupUploadZone() {
  // Click to open file picker
  uploadZone.addEventListener('click', (e) => {
    if (e.target === removeFileBtn || removeFileBtn.contains(e.target)) return;
    if (selectedFile) return; // Don't re-open picker when file is selected
    fileInput.click();
  });

  // File selected via picker
  fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
      handleFile(e.target.files[0]);
    }
  });

  // Drag and drop
  uploadZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    if (!selectedFile) {
      uploadZone.classList.add('drag-over');
      // Update text to indicate drop
      const textElem = uploadPrompt.querySelector('.upload-zone__text');
      if (textElem) textElem.textContent = "Drop it here";
    }
  });

  uploadZone.addEventListener('dragleave', (e) => {
    e.preventDefault();
    uploadZone.classList.remove('drag-over');
    const textElem = uploadPrompt.querySelector('.upload-zone__text');
    if (textElem) textElem.textContent = "Drop your .srt file here";
  });

  uploadZone.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadZone.classList.remove('drag-over');
    const textElem = uploadPrompt.querySelector('.upload-zone__text');
    if (textElem) textElem.textContent = "Drop your .srt file here";
    
    if (e.dataTransfer.files.length > 0) {
      handleFile(e.dataTransfer.files[0]);
    }
  });

  // Remove file
  removeFileBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    clearFile();
  });
}

function handleFile(file) {
  hideUploadError();
  hideError();

  // Validate extension
  if (!file.name.toLowerCase().endsWith('.srt')) {
    showUploadError('Please upload an .srt file');
    uploadZone.classList.add('error');
    return;
  }

  // Validate file size
  if (file.size > MAX_FILE_SIZE) {
    showUploadError("This file seems too large for an SRT — double-check it's the right file.");
    uploadZone.classList.add('error');
    return;
  }

  // Validate empty file (zero bytes)
  if (file.size === 0) {
    showUploadError("This SRT file appears to be empty.");
    uploadZone.classList.add('error');
    return;
  }

  selectedFile = file;

  // Update UI — show file card, hide prompt
  uploadPrompt.style.display = 'none';
  fileCard.style.display = 'flex';
  fileName.textContent = file.name;
  fileSize.textContent = formatFileSize(file.size);
  uploadZone.classList.add('has-file');
  uploadZone.classList.remove('error');

  // Reset any previous results
  resetResults();
  updateConvertButton();
}

function clearFile() {
  selectedFile = null;
  fileInput.value = '';

  uploadPrompt.style.display = '';
  fileCard.style.display = 'none';
  uploadZone.classList.remove('has-file');
  uploadZone.classList.remove('error');

  hideUploadError();
  resetResults();
  updateConvertButton();
}

function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}


// ─── Event Listeners ─────────────────────────────────────────────────────────

function setupEventListeners() {
  convertBtn.addEventListener('click', startConversion);
  downloadBtn.addEventListener('click', downloadResult);
  resetLink.addEventListener('click', resetPage);

  errorClose.addEventListener('click', () => {
    hideError();
  });
  
  // Smooth scroll links
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
      e.preventDefault();
      const target = document.querySelector(this.getAttribute('href'));
      if (target) {
        target.scrollIntoView({
          behavior: 'smooth'
        });
      }
    });
  });
}

function updateConvertButton() {
  convertBtn.disabled = !selectedFile || isConverting;
}


// ─── Conversion ──────────────────────────────────────────────────────────────

async function startConversion() {
  if (!selectedFile || isConverting) return;

  isConverting = true;
  hideError();
  resetResults();

  // Update button to loading state
  convertLabel.textContent = 'Converting your subtitles...';
  convertSpinner.style.display = '';
  convertBtn.disabled = true;
  convertBtn.classList.add('converting');

  // Show progress section
  progressSection.style.display = '';
  progressBar.style.width = '2%';
  progressText.textContent = 'Uploading file...';
  
  // Show progress notice and set a timer to hide it after 15 seconds
  progressNotice.style.display = '';
  const noticeTimeout = setTimeout(() => {
    progressNotice.style.display = 'none';
  }, 15000);

  try {
    const formData = new FormData();
    formData.append('file', selectedFile);

    // Simulate progress during the API call
    const progressInterval = simulateProgress();

    const response = await fetch(`${BACKEND_URL}/api/convert`, {
      method: 'POST',
      body: formData,
    });

    clearInterval(progressInterval);

    if (!response.ok) {
      let errorMessage = 'Conversion failed. Please try again — if this keeps happening, the server may be waking up. Wait 30 seconds and retry.';
      try {
        const errorData = await response.json();
        if (errorData.detail) {
          errorMessage = errorData.detail;
        } else if (errorData.error) {
          errorMessage = errorData.error;
        }
      } catch (_) {}
      throw new Error(errorMessage);
    }

    const result = await response.json();

    // Complete progress
    progressBar.style.width = '100%';
    progressText.textContent = 'Conversion complete!';

    // Store result for download
    convertedSrtContent = result.srt_content;
    originalFilename = result.original_filename;

    // Brief pause to show 100% progress, then show results
    await delay(500);
    progressSection.style.display = 'none';

    // Show success banner
    const totalConverted = result.stats ? result.stats.total_lines - result.stats.unconverted_count : 0;
    successBannerText.textContent = `Conversion complete — ${totalConverted} subtitle lines converted`;

    // Show results
    renderPreview(result.preview);

    // Show unconverted notice warning if present
    if (result.warnings && result.warnings.length > 0) {
      // Find the warning containing "A few lines couldn't be converted"
      const userWarning = result.warnings.find(w => w.includes("couldn't be converted") || w.includes("misaligned"));
      if (userWarning) {
        unconvertedNotice.textContent = userWarning;
        unconvertedNotice.style.display = '';
      }
    }

    resultSection.style.display = '';
    resultSection.scrollIntoView({ behavior: 'smooth' });

  } catch (err) {
    progressSection.style.display = 'none';
    showError(err.message);
    // Smooth scroll back to inline error
    errorInline.scrollIntoView({ behavior: 'smooth' });
  } finally {
    clearTimeout(noticeTimeout);
    progressNotice.style.display = 'none';
    isConverting = false;
    convertLabel.textContent = 'Convert your subtitles →';
    convertSpinner.style.display = 'none';
    convertBtn.classList.remove('converting');
    updateConvertButton();
  }
}

function simulateProgress() {
  let progress = 5;
  const interval = setInterval(() => {
    if (progress < 90) {
      // Slow down progressively
      const increment = progress < 30 ? 4 : progress < 60 ? 2 : 1;
      progress = Math.min(90, progress + increment);
      progressBar.style.width = progress + '%';

      // Update text with estimated section count
      const totalSections = Math.max(5, Math.floor(selectedFile.size / 3000) || 5);
      const currentSection = Math.min(totalSections - 1, Math.floor((progress / 100) * totalSections));
      progressText.textContent = `Processing section ${currentSection} of ${totalSections}...`;
    }
  }, 750);

  return interval;
}


// ─── Preview Rendering ───────────────────────────────────────────────────────

function renderPreview(preview) {
  if (!preview || preview.length === 0) return;

  previewRows.innerHTML = '';

  // Show up to 5 lines as specified
  const items = preview.slice(0, 5);
  items.forEach((item) => {
    const row = document.createElement('div');
    row.className = 'preview__row';
    row.innerHTML = `
      <div class="preview__cell preview__cell--original">${escapeHtml(item.original)}</div>
      <div class="preview__cell preview__cell--converted">${escapeHtml(item.converted)}</div>
    `;
    previewRows.appendChild(row);
  });
}


// ─── Download ────────────────────────────────────────────────────────────────

function downloadResult() {
  if (!convertedSrtContent) return;

  const blob = new Blob([convertedSrtContent], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);

  let downloadName = 'converted_hinglish.srt';
  if (originalFilename) {
    const base = originalFilename.replace(/\.srt$/i, '');
    downloadName = `${base}_hinglish.srt`;
  }

  const a = document.createElement('a');
  a.href = url;
  a.download = downloadName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}


// ─── Reset / Convert Another ─────────────────────────────────────────────────

function resetPage() {
  // Fade out results
  resultSection.classList.add('fade-out');

  setTimeout(() => {
    resultSection.style.display = 'none';
    resultSection.classList.remove('fade-out');

    // Reset everything
    clearFile();
    resetResults();

    // Fade in upload section
    uploadSection.classList.add('fade-in');
    setTimeout(() => {
      uploadSection.classList.remove('fade-in');
    }, 400);
    
    // Scroll back to tool container
    const toolContainer = document.querySelector('.tool-container');
    if (toolContainer) toolContainer.scrollIntoView({ behavior: 'smooth' });
  }, 300);
}


// ─── Error Handling ──────────────────────────────────────────────────────────

function showError(message) {
  errorText.textContent = message;
  errorInline.classList.add('active');
}

function hideError() {
  errorInline.classList.remove('active');
}

function showUploadError(message) {
  uploadErrorText.textContent = message;
  uploadError.style.display = 'flex';
}

function hideUploadError() {
  uploadError.style.display = 'none';
}


// ─── Utilities ───────────────────────────────────────────────────────────────

function resetResults() {
  convertedSrtContent = null;
  originalFilename = null;
  resultSection.style.display = 'none';
  progressSection.style.display = 'none';
  unconvertedNotice.style.display = 'none';
  progressBar.style.width = '0%';
  previewRows.innerHTML = '';
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}
