(() => {
  document.querySelectorAll('textarea.rich-editor').forEach(field => {
    field.required = false;
    if (!window.CKEDITOR) {
      const note = document.createElement('p');
      note.className = 'muted';
      note.textContent = '편집기를 불러오지 못했습니다. 아래 입력란에서 내용을 작성할 수 있습니다.';
      field.before(note);
      return;
    }
    CKEDITOR.replace(field.id, {
      language: 'ko', height: 320,
      removePlugins: 'image,flash,iframe,forms',
      toolbar: [
        {name: 'document', items: ['Source']},
        {name: 'clipboard', items: ['Undo', 'Redo']},
        {name: 'basicstyles', items: ['Bold', 'Italic', 'Underline', 'Strike', 'RemoveFormat']},
        {name: 'paragraph', items: ['NumberedList', 'BulletedList', 'Blockquote', 'JustifyLeft', 'JustifyCenter', 'JustifyRight']},
        {name: 'links', items: ['Link', 'Unlink']},
        {name: 'insert', items: ['Table', 'HorizontalRule']},
        {name: 'styles', items: ['Format']},
      ],
      contentsCss: [CKEDITOR.getUrl('contents.css')],
    });
  });
  document.querySelectorAll('.rich-form').forEach(form => {
    form.addEventListener('submit', () => {
      if (window.CKEDITOR) Object.values(CKEDITOR.instances).forEach(editor => editor.updateElement());
    });
  });
})();
