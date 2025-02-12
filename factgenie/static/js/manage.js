const url_prefix = window.url_prefix;
const modelOutputs = window.model_outputs;

function showModelOutputs(dataset, split) {
    // add a row to #model-out-table for each model output
    const outputs = modelOutputs[dataset][split];
    const table = $('#model-out-table tbody');
    table.empty();

    for (const setup in outputs) {
        const examples = outputs[setup].example_count;
        const row = `<tr>
            <td><a class="blue-link" href="${url_prefix}/browse?dataset=${dataset}&split=${split}&example_idx=0">${setup}</a></td>
            <td>${examples}</td>
            <td>
                <a onclick="deleteOutput('${dataset}', '${split}', '${setup}')" class="btn btn-outline-danger"
                data-bs-toggle="tooltip" title="Delete the output">
                <i class="fa fa-trash"></i>
                </a>
            </td>
        </tr>`;
        table.append(row);
    }
}

function deleteOutput(dataset, split, setup) {
    // ask for confirmation
    if (!confirm(`Are you sure you want to delete the output for ${setup}?`)) {
        return;
    }
    $.post({
        url: `${url_prefix}/delete_model_outputs`,
        contentType: 'application/json', // Specify JSON content type
        data: JSON.stringify({
            dataset: dataset,
            split: split,
            setup: setup
        }),
        success: function (response) {
            console.log(response);

            if (response.success !== true) {
                alert(response.error);
            } else {
                // reload
                location.reload();
            }
        }
    });
}

function changeDataset() {
    const dataset = $('#dataset-select').val();

    // set available splits in #split-select
    $('#split-select').empty();
    for (const split of datasets[dataset].splits) {
        $('#split-select').append(`<option value="${split}">${split}</option>`);
    }
    const split = $('#split-select').val();

    showModelOutputs(dataset, split);
}

function changeSplit() {
    const dataset = $('#dataset-select').val();
    const split = $('#split-select').val();

    showModelOutputs(dataset, split);
}


$("#dataset-select").on("change", changeDataset);
$("#split-select").on("change", changeSplit);

function enableTooltips() {
    // enable tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'))
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl)
    })
}


$(document).ready(function () {
    $("#dataset-select").val(Object.keys(datasets)[0]).trigger("change");
    $("#page-input").val(example_idx);
    enableTooltips();
});

