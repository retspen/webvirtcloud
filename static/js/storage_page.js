// A storage pool's page (storage.html): the volume Clone dialog, a refused
// new volume's dialog, and the ISO upload in chunks.

// the clone dialog: filled for the volume whose button opened it, its
// choices reset; the format rows show while converting
function showCloneRows() {
    var convert = $('#clone-convert').prop('checked');
    $('#clone-format-row').toggleClass('d-none', !convert);
    $('#clone-prealloc-row').toggleClass('d-none', !(convert && $('#clone-format').val() == 'qcow2'));
}
$('#CloneVolume').on('show.bs.modal', function (event) {
    var volume = event.relatedTarget.dataset.volume;
    $('#clone-image').val(volume);
    $('#clone-image-name').text(volume);
    $('#clone-name').val('');
    $('#clone-convert, #clone-prealloc').prop('checked', false);
    $('#clone-format').val('raw');
    showCloneRows();
});
$('#clone-convert, #clone-format').on('change', showCloneRows);

// a refused new volume: its dialog opens again on what was entered, at the refused field
var addImage = document.getElementById('AddImage');
if (addImage && addImage.hasAttribute('data-open')) {
    addImage.addEventListener('shown.bs.modal', focusFirstError, {once: true});
    bootstrap.Modal.getOrCreateInstance(addImage).show();
}

$(document).ready(function() {
    var pendingUpload = null;
    var uploadInProgress = false;
    // the browser sends the file: leaving the page stops the upload
    window.addEventListener('beforeunload', function(e) {
        if (uploadInProgress) { e.preventDefault(); e.returnValue = ''; }
    });
    $('#isoUploadForm').on('submit', function(e) {
        e.preventDefault();
        // the form's messages and token; it is sent to this page
        var form = this;
        var texts = form.dataset;
        if (uploadInProgress) return;

        var fileInput = $('#id_file')[0];
        var errorMessage = $('#upload-error-message');
        if (fileInput.files.length === 0) {
            errorMessage.text(texts.noFile).removeClass("d-none");
            return;
        }

        var file = fileInput.files[0];
        var fileName = file.name;
        if (!/\.iso$/i.test(fileName) || fileName.length <= 4) {
            errorMessage.text(texts.notIso).removeClass("d-none");
            return;
        }
        if (file.size === 0) {
            errorMessage.text(texts.empty).removeClass("d-none");
            return;
        }
        var chunkSize = 32 * 1024 * 1024; // Fewer SSH connections per upload
        var totalChunks = Math.ceil(file.size / chunkSize);
        var fileSignature = [fileName, file.size, file.lastModified].join(':');
        if (!pendingUpload || pendingUpload.signature !== fileSignature) {
            pendingUpload = {
                signature: fileSignature,
                chunkIndex: 0,
                uploadId: (window.crypto && window.crypto.randomUUID) ? window.crypto.randomUUID() : (Date.now() + '-' + Math.random().toString(36).substring(2, 10))
            };
        }
        var chunkIndex = pendingUpload.chunkIndex;
        var uploadId = pendingUpload.uploadId;
        var retryCount = 0;
        uploadInProgress = true;

        var uploadDialog = bootstrap.Modal.getOrCreateInstance(document.getElementById('IsoUpload'));
        var uploadStatus = $('#upload-status');
        var uploadStatusText = $('#upload-status-text');
        var uploadButton = $('#isoUploadForm button[type="submit"]');

        errorMessage.addClass("d-none");
        uploadStatusText.text(texts.starting);
        uploadStatus.removeClass('d-none').addClass('d-flex');
        uploadButton.prop('disabled', true);

        function uploadChunk() {
            if (chunkIndex >= totalChunks) {
                return;
            }

            var start = chunkIndex * chunkSize;
            var end = Math.min(start + chunkSize, file.size);
            var chunk = file.slice(start, end);

            var formData = new FormData();
            formData.append('file', chunk, fileName);
            formData.append('file_name', fileName);
            formData.append('chunk_index', chunkIndex);
            formData.append('total_chunks', totalChunks);
            formData.append('file_size', file.size);
            formData.append('upload_id', uploadId);
            formData.append('iso_upload', 'true');
            formData.append('csrfmiddlewaretoken', form.elements.csrfmiddlewaretoken.value);

            $.ajax({
                url: form.action,
                type: 'POST',
                data: formData,
                processData: false,
                contentType: false,
                // anything else is not a stored chunk: a redirect to an HTML page (the host did
                // not answer, the session ended) is an error, not a success
                dataType: 'json',
                success: function(data) {
                    if (chunkIndex === 0) {
                        // the job panel follows the upload from here
                        window.resourceJobPanel.track(data.job);
                        uploadStatusText.text(texts.uploading);
                        uploadDialog.hide();
                    }
                    retryCount = 0;
                    chunkIndex++;
                    pendingUpload.chunkIndex = chunkIndex;

                    if (chunkIndex < totalChunks) {
                        uploadChunk();
                    } else {
                        pendingUpload = null;
                        uploadInProgress = false;
                        uploadStatus.removeClass('d-flex').addClass('d-none');
                        uploadButton.prop('disabled', false);
                    }
                },
                error: function(jqXHR, textStatus, errorThrown) {
                    if ((jqXHR.status === 0 || jqXHR.status === 429 || jqXHR.status >= 500) && retryCount < 3) {
                        retryCount++;
                        uploadStatusText.text(texts.retrying);
                        setTimeout(uploadChunk, 1000 * Math.pow(2, retryCount - 1));
                        return;
                    }
                    uploadInProgress = false;
                    uploadStatus.removeClass('d-flex').addClass('d-none');
                    uploadButton.prop('disabled', false);
                    if (jqXHR.status >= 400 && jqXHR.status < 500 && jqXHR.status !== 429) {
                        pendingUpload = null;
                    }
                    var errorText = jqXHR.responseJSON && jqXHR.responseJSON.error ? jqXHR.responseJSON.error : texts.failed;
                    errorMessage.text(errorText).removeClass("d-none");
                    uploadDialog.show();
                }
            });
        }
        uploadChunk();
    });
});
