import os


def find_file_by_id(file_id: str, folder="tmp"):
    for fname in os.listdir(folder):
        if fname.startswith(file_id + "_"):
            return os.path.join(folder, fname)
    return None


def find_file_ext(file_path: str):
    return os.path.splitext(file_path)[1]
