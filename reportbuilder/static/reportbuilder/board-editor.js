(() => {
  const fields = [...document.querySelectorAll('textarea.rich-editor')];
  if (!fields.length) return;
  const $ = window.jQuery;
  fields.forEach(field => {
    field.required = false;
    if (!$ || !$.fn.summernote || !window.boardEditorSafety) {
      const note = document.createElement('p');
      note.className = 'muted editor-fallback';
      note.setAttribute('role', 'status');
      note.textContent = '편집기를 불러오지 못했습니다. 아래 입력란에서 내용을 작성할 수 있습니다.';
      field.before(note);
      return;
    }
    const label = document.querySelector(`label[for="${field.id}"]`);
    $(field).summernote({
      lang: 'ko-KR',
      height: Number(field.getAttribute('rows')) <= 6 ? 220 : 320,
      minHeight: 180,
      dialogsInBody: false,
      disableDragAndDrop: true,
      disableLinkTarget: true,
      pasteAllowImage: false,
      shortcuts: false,
      tabDisable: true,
      codeviewFilter: true,
      codeviewIframeFilter: true,
      styleTags: ['p', 'blockquote', 'pre', 'h2', 'h3', 'h4'],
      toolbar: [
        ['history', ['undo', 'redo']],
        ['style', ['style']],
        ['font', ['bold', 'italic', 'underline', 'strikethrough', 'clear']],
        ['para', ['ul', 'ol', 'paragraph']],
        ['insert', ['link', 'picture', 'video', 'table', 'hr']],
        ['view', ['codeview']],
      ],
      popover: {image: [['remove', ['removeMedia']]], link: [['link', ['linkDialogShow', 'unlink']]],
        table: [['add', ['addRowDown', 'addRowUp', 'addColLeft', 'addColRight']],
          ['delete', ['deleteRow', 'deleteCol', 'deleteTable']]]},
      callbacks: {
        onInit() {
          const context = $(field).data('summernote');
          context.modules.codeview.purify = window.boardEditorSafety.sanitize;
          const createVideo = context.modules.videoDialog.createVideoNode.bind(context.modules.videoDialog);
          context.modules.videoDialog.createVideoNode = url => {
            const node = createVideo(url);
            if (!node) return null;
            const safe = window.boardEditorSafety.sanitize(node.outerHTML);
            const template = document.createElement('template');
            template.innerHTML = safe;
            const video = template.content.querySelector('iframe');
            if (!video) window.alert('YouTube 또는 Vimeo 동영상 주소를 입력해 주세요.');
            return video;
          };
          const editor = $(field).next('.note-editor');
          editor.find('input[type=file]').attr('accept', 'image/png,image/jpeg,image/gif,image/webp')
            .siblings('label').text('파일 선택 (PNG/JPEG/GIF/WebP, 64KB 이하)');
          editor.find('.note-video-url').siblings('label').find('small').text('YouTube, Vimeo');
          editor.find('button[aria-label="' + $.summernote.lang['ko-KR'].image.image + '"]').attr('aria-label', 'Picture');
          editor.find('button[aria-label="' + $.summernote.lang['ko-KR'].video.video + '"]').attr('aria-label', 'Video');
          editor.find('.btn-codeview').attr('aria-label', 'Code View');
          const editable = $(field).next('.note-editor').find('.note-editable')[0];
          editable.setAttribute('role', 'textbox');
          editable.setAttribute('aria-multiline', 'true');
          editable.setAttribute('aria-label', label ? label.textContent.replace(/:\s*$/, '') : '내용');
          editable.id = `${field.id}-editable`;
          if (label) label.htmlFor = editable.id;
          $(field).next('.note-editor').find('.note-modal .close')
            .removeAttr('aria-hidden').attr('aria-label', '닫기');
        },
        onChange(contents) { field.value = contents; },
        onImageLinkInsert(url) {
          const safe = window.boardEditorSafety.imageURL(url);
          if (safe) $(field).summernote('insertImage', safe);
          else window.alert('이미지는 HTTPS 주소로 등록해 주세요.');
        },
        onImageUpload(files) {
          [...files].forEach(file => {
            if (file.size > 64 * 1024 || !['image/png', 'image/jpeg', 'image/gif', 'image/webp'].includes(file.type)) {
              window.alert('PNG, JPEG, GIF, WebP 이미지를 64KB 이하로 선택해 주세요. 큰 이미지는 HTTPS 주소로 등록할 수 있습니다.');
              return;
            }
            const reader = new FileReader();
            reader.onload = () => $(field).summernote('insertImage', reader.result);
            reader.readAsDataURL(file);
          });
        },
        onPaste(event) {
          const clipboard = (event.originalEvent || event).clipboardData;
          if (!clipboard) return;
          // Pasted HTML must not execute before server validation.
          event.preventDefault();
          $(field).summernote('insertText', clipboard.getData('text/plain'));
        },
      },
    });
  });
  document.querySelectorAll('.rich-form').forEach(form => {
    form.addEventListener('submit', () => {
      fields.filter(field => field.form === form).forEach(field => {
        if ($ && $.fn.summernote && $(field).data('summernote')) {
          field.value = window.boardEditorSafety.sanitize($(field).summernote('code'));
        }
      });
    });
  });
})();
