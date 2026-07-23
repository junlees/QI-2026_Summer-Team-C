import os
from torch.utils.data import DataLoader
from torchvision import datasets, transforms
from base import BaseDataLoader

# ImageNet 사전학습 통계 (GoogLeNet transform_input=True와 조합되어 [-1,1] 범위로 매핑됨)
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]


class PlantVillageDataLoader(BaseDataLoader):
    """PlantVillage 데이터로더 (train/valid/test 3-way split).

    data_dir 아래 train/ valid/ test/ 폴더를 가정한다(ImageFolder 구조).
    - split='train'         : 학습 증강 전처리
    - split='valid'/'test'  : 평가 전처리(리사이즈 + 센터크롭)
    train.py 는 split_validation()으로 valid/ 로더를, test.py 는 split='test'로 test/ 로더를 쓴다.
    """

    def __init__(self, data_dir, batch_size, shuffle=True,
                 validation_split=0.0, num_workers=1, split='train'):
        self.data_dir = data_dir
        self.split = split

        # 학습: RandomResizedCrop(224) + 수평뒤집기 (표준 ImageNet fine-tuning)
        self.train_trsfm = transforms.Compose([
            transforms.RandomResizedCrop(224, scale=(0.8, 1.0)),
            transforms.RandomHorizontalFlip(),
            transforms.ToTensor(),
            transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
        ])
        # 평가: 256 리사이즈 후 중앙 224 크롭 (GoogLeNet 입력 224)
        self.valid_trsfm = transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
        ])

        trsfm = self.train_trsfm if split == 'train' else self.valid_trsfm
        self.dataset = datasets.ImageFolder(os.path.join(data_dir, split), transform=trsfm)
        super().__init__(self.dataset, batch_size, shuffle, validation_split, num_workers)

    def split_validation(self):
        """valid/ 폴더에 대한 평가용 DataLoader 반환 (eval 전처리, 셔플 없음)."""
        valid_ds = datasets.ImageFolder(os.path.join(self.data_dir, 'valid'),
                                        transform=self.valid_trsfm)
        # train/valid 의 클래스 인덱스 순서가 동일해야 라벨이 일치한다.
        assert self.dataset.classes == valid_ds.classes, \
            "train/valid class ordering mismatch"
        num_workers = self.init_kwargs['num_workers']
        return DataLoader(
            valid_ds,
            batch_size=self.init_kwargs['batch_size'],
            shuffle=False,
            num_workers=num_workers,
            pin_memory=True,
            persistent_workers=num_workers > 0,
        )
