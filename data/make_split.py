"""dataset/ -> split/{train,val,test} (70/15/15) 생성 스크립트."""
import os
import random
import shutil

random.seed(42)
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "dataset")
OUT = os.path.join(HERE, "split")


def main():
    classes = sorted(os.listdir(SRC))
    for split in ["train", "val", "test"]:
        for c in classes:
            os.makedirs(os.path.join(OUT, split, c), exist_ok=True)

    for c in classes:
        files = sorted(os.listdir(os.path.join(SRC, c)))
        random.shuffle(files)
        n = len(files)
        n_train = int(n * 0.7)
        n_val = int(n * 0.15)
        splits = {
            "train": files[:n_train],
            "val": files[n_train:n_train + n_val],
            "test": files[n_train + n_val:],
        }
        for split, flist in splits.items():
            for f in flist:
                shutil.copy(os.path.join(SRC, c, f), os.path.join(OUT, split, c, f))
        print(c, {k: len(v) for k, v in splits.items()})


if __name__ == "__main__":
    main()
