(() => {
  const fields = [...document.querySelectorAll('textarea.rich-editor')];
  if (!fields.length) return;
  const $ = window.jQuery;
  fields.forEach(field => {
    field.required = false;
    if (!$ || !$.fn.summernote) {
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
        ['insert', ['link', 'table', 'hr']],
      ],
      popover: {image: [], link: [['link', ['linkDialogShow', 'unlink']]],
        table: [['add', ['addRowDown', 'addRowUp', 'addColLeft', 'addColRight']],
          ['delete', ['deleteRow', 'deleteCol', 'deleteTable']]]},
      callbacks: {
        onInit() {
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
          field.value = $(field).summernote('code');
        }
      });
    });
  });
})();
