import torch.nn as nn
from torchvision import models
from torchvision.models import GoogLeNet_Weights, ViT_B_16_Weights
from base import BaseModel


class GoogLeNetPlant(BaseModel):
    """ImageNet 사전학습 GoogLeNet(InceptionV1)을 PlantVillage 38클래스로 fine-tuning.

    loss1/loss2/loss3 분류기(각각 aux1.fc2, aux2.fc2, fc)를 num_classes 출력으로 교체한다.
    freeze 없이 전 계층을 학습(전체 fine-tune)한다.
    """

    def __init__(self, num_classes=38, pretrained=True):
        super().__init__()
        weights = GoogLeNet_Weights.IMAGENET1K_V1 if pretrained else None
        # aux_logits=True 필수: aux1/aux2(loss1/loss2 분류기)가 생성되고,
        # 사전학습 가중치 로드 시 transform_input도 자동 True가 된다
        # (DataLoader의 ImageNet 정규화와 조합되어 [-1,1] 범위로 매핑됨).
        self.backbone = models.googlenet(weights=weights, aux_logits=True)

        # 사전학습 로드 후 3개 분류기를 num_classes 출력으로 교체
        # (교체된 Linear만 scratch 학습, 나머지 계층은 fine-tune).
        self.backbone.aux1.fc2 = nn.Linear(self.backbone.aux1.fc2.in_features, num_classes)  # loss1
        self.backbone.aux2.fc2 = nn.Linear(self.backbone.aux2.fc2.in_features, num_classes)  # loss2
        self.backbone.fc = nn.Linear(self.backbone.fc.in_features, num_classes)              # loss3

    def forward(self, x):
        # train(): GoogLeNetOutputs(logits, aux_logits2, aux_logits1) namedtuple
        # eval() : logits Tensor
        return self.backbone(x)


class ViTPlant(BaseModel):
    """ImageNet 사전학습 ViT-B/16을 PlantVillage 분류로 fine-tuning.

    분류 헤드(heads.head)를 num_classes 출력으로 교체하고 전 계층을 fine-tune한다.
    GoogLeNet과 달리 **aux 출력이 없어 train()/eval() 모두 logits Tensor를 반환**한다
    (loss는 cross_entropy, metric은 그대로 동작). ViT는 transform_input이 없으므로
    DataLoader의 ImageNet 정규화(입력 224)를 그대로 사용하면 된다 — GoogLeNet 특유의 함정 없음.
    """

    def __init__(self, num_classes=38, pretrained=True):
        super().__init__()
        weights = ViT_B_16_Weights.IMAGENET1K_V1 if pretrained else None
        self.backbone = models.vit_b_16(weights=weights)
        # heads.head(Linear 768→1000)를 num_classes 출력으로 교체
        in_f = self.backbone.heads.head.in_features
        self.backbone.heads.head = nn.Linear(in_f, num_classes)

    def forward(self, x):
        return self.backbone(x)   # train/eval 모두 logits Tensor
