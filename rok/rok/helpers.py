def wrap_labels(labels: dict):
    labels_list = []
    for key, value in labels.items():
        item = {
            "key": key,
            "value": value
        }
        labels_list.append(item)

    return labels_list
