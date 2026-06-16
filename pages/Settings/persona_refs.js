const REF_PREVIEW_CONCURRENCY = 5;

const isDataImage = ref => String(ref).startsWith('data:image');
const isRemoteImageRef = ref => /^https?:\/\//.test(String(ref));
const refDisplayName = (ref, index) =>
  isDataImage(ref) ? `图片 ${index + 1}` : (String(ref).split(/[\/\\]/).pop() || String(ref)).slice(0, 32);

export function createPersonaRefController({ $, bridge, previewCache, markDirty, showToast }) {
  let refs = [];
  let uploadTask = null;
  let previewActive = 0;
  const previewQueue = [];
  const previewRequests = new Map();

  const visibleRefs = () => refs.filter(ref => !isDataImage(ref)).join('\n');

  const syncTextarea = () => {
    const el = $('modal-refs');
    if (el) el.value = visibleRefs();
  };

  const runPreviewQueue = () => {
    while (previewActive < REF_PREVIEW_CONCURRENCY && previewQueue.length) {
      const item = previewQueue.shift();
      previewActive++;
      Promise.resolve()
        .then(item.task)
        .then(item.resolve, item.reject)
        .finally(() => {
          previewActive--;
          runPreviewQueue();
        });
    }
  };

  const queueRefPreview = task => new Promise((resolve, reject) => {
    previewQueue.push({ task, resolve, reject });
    runPreviewQueue();
  });

  const getLocalRefPreview = path => {
    if (previewCache[path]) {
      return Promise.resolve(previewCache[path]);
    }
    if (previewRequests.has(path)) {
      return previewRequests.get(path);
    }

    const requestTask = queueRefPreview(async () => {
      const response = await bridge.apiGet('get_image_b64', { path });
      const imageData = typeof response === 'string'
        ? response
        : (response?.image_data || response?.data);
      if (!imageData || !String(imageData).startsWith('data:image/')) {
        throw new Error(response?.error || 'preview response contained no image');
      }
      previewCache[path] = imageData;
      return imageData;
    }).finally(() => {
      previewRequests.delete(path);
    });

    previewRequests.set(path, requestTask);
    return requestTask;
  };

  const loadLocalRefPreview = async (ref, img, state) => {
    const src = await getLocalRefPreview(ref);
    if (!img.isConnected) return;
    img.src = src;
    img.style.display = 'block';
    state.style.display = 'none';
  };

  const createRefPreviewItem = (ref, index) => {
    const value = String(ref);
    const isInline = isDataImage(value);
    const isRemote = isRemoteImageRef(value);
    const name = refDisplayName(value, index);

    const wrap = document.createElement('div');
    wrap.className = 'ref-image-item';
    wrap.title = isInline ? name : value;

    const img = document.createElement('img');
    img.className = 'ref-image';
    img.alt = name;
    img.loading = 'lazy';

    const state = document.createElement('div');
    state.className = 'ref-image-state';
    state.style.display = 'none';

    const nameDiv = document.createElement('div');
    nameDiv.className = 'ref-image-name';
    nameDiv.textContent = name;

    const delBtn = document.createElement('button');
    delBtn.className = 'ref-image-del';
    delBtn.title = '删除';
    delBtn.textContent = '删除';
    delBtn.addEventListener('click', () => {
      refs.splice(index, 1);
      syncTextarea();
      renderRefPreviews();
      markDirty();
    });

    img.onerror = () => {
      img.style.display = 'none';
      state.style.display = 'flex';
      state.classList.add('is-error');
      state.textContent = '图片加载失败';
    };

    if (isInline || isRemote) {
      img.src = value;
    } else if (previewCache[value]) {
      img.src = previewCache[value];
    } else {
      img.style.display = 'none';
      state.style.display = 'flex';
      state.textContent = '图片加载中...';
      loadLocalRefPreview(value, img, state).catch(e => {
        if (!state.isConnected) return;
        state.classList.add('is-error');
        state.textContent = `图片加载失败：${e}`;
      });
    }

    wrap.append(delBtn, img, state, nameDiv);
    return wrap;
  };

  function renderRefPreviews(nextRefs = refs) {
    refs = [...(nextRefs || [])];
    const el = $('modal-ref-previews');
    if (!el) return;
    el.innerHTML = '';
    if (!refs.length) {
      el.innerHTML = '<div class="ref-empty">暂无参考图，可从右上角上传或在左侧粘贴路径</div>';
      return;
    }

    refs.forEach((ref, index) => el.appendChild(createRefPreviewItem(ref, index)));
  }

  const readFileAsDataURL = file => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error(`${file.name} 读取失败`));
    reader.readAsDataURL(file);
  });

  const uploadRefFile = async file => {
    const previewUrl = URL.createObjectURL(file);
    try {
      const data = await bridge.upload('upload_ref_image', file);
      if (!data || !data.success || !data.path) {
        throw new Error(data?.error || `${file.name} 上传失败`);
      }
      previewCache[data.path] = previewUrl;
      return data.path;
    } catch (multipartError) {
      try {
        const dataUrl = await readFileAsDataURL(file);
        const data = await bridge.apiPost('upload_ref_image_b64', {
          filename: file.name,
          data: dataUrl,
        });
        if (!data || !data.success || !data.path) {
          throw new Error(data?.error || `${file.name} 上传失败`);
        }
        previewCache[data.path] = previewUrl;
        return data.path;
      } catch (fallbackError) {
        URL.revokeObjectURL(previewUrl);
        throw new Error(`${multipartError}; fallback: ${fallbackError}`);
      }
    }
  };

  async function uploadRefImages(files) {
    const btn = $('modal-upload-btn');
    const status = $('modal-upload-status');
    if (!files || !files.length) return;

    const fileArr = Array.from(files);
    const oversized = fileArr.filter(file => file.size > 20 * 1024 * 1024);
    if (oversized.length) {
      status.textContent = `✗ ${oversized.map(file => file.name).join(', ')} 超过 20MB`;
      status.className = 'upload-status err';
      return;
    }

    btn.disabled = true;
    status.textContent = `上传中 (0/${fileArr.length})...`;
    status.className = 'upload-status uploading';

    const task = (async () => {
      let done = 0;
      for (const file of fileArr) {
        const path = await uploadRefFile(file);
        refs.push(path);
        done++;
        status.textContent = `上传中 (${done}/${fileArr.length})...`;
        syncTextarea();
        renderRefPreviews();
      }
    })();
    uploadTask = task;
    try {
      await task;
      status.textContent = `✓ 已添加 ${fileArr.length} 张图片`;
      status.className = 'upload-status ok';
      markDirty();
      setTimeout(() => { status.textContent=''; status.className='upload-status'; }, 2000);
    } catch (e) {
      status.textContent = `✗ ${e}`;
      status.className = 'upload-status err';
    } finally {
      if (uploadTask === task) uploadTask = null;
      btn.disabled = false;
    }
  }

  const bind = () => {
    const clearRefsBtn = $('modal-clear-refs-btn');
    if (clearRefsBtn) {
      clearRefsBtn.addEventListener('click', () => {
        refs = [];
        syncTextarea();
        renderRefPreviews();
        markDirty();
      });
    }

    const uploadBtn = $('modal-upload-btn');
    const fileInput = $('modal-file-input');
    if (uploadBtn && fileInput) {
      uploadBtn.addEventListener('click', () => fileInput.click());
      fileInput.addEventListener('change', () => {
        if (fileInput.files && fileInput.files.length) {
          uploadRefImages(fileInput.files);
          fileInput.value = '';
        }
      });
    }

    const modalRefs = $('modal-refs');
    if (modalRefs) {
      modalRefs.addEventListener('input', () => {
        const textPart = modalRefs.value.split('\n').map(s => s.trim()).filter(Boolean);
        const b64Part = refs.filter(isDataImage);
        refs = [...b64Part, ...textPart];
        renderRefPreviews();
      });
    }
  };

  return {
    bind,
    setRefs(nextRefs) {
      refs = [...(nextRefs || [])];
      syncTextarea();
      renderRefPreviews();
    },
    refs() {
      return refs.filter(Boolean);
    },
    async waitForUpload() {
      if (uploadTask) await uploadTask;
    },
    renderRefPreviews,
    uploadRefImages,
    getLocalRefPreview,
  };
}
