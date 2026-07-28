import torch
import torch.nn.functional as F


def cross_entropy(output, target, label_smoothing=0.0):
    """단일 텐서 출력 모델(ViT 등)용 표준 교차엔트로피 손실(raw logits 입력)."""
    return F.cross_entropy(output, target, label_smoothing=label_smoothing)


def googlenet_loss(output, target, aux_weight=0.3):
    """GoogLeNet 결합 손실: loss3 + 0.3 * (loss1 + loss2).

    - train(): output은 GoogLeNetOutputs(logits, aux_logits2, aux_logits1) namedtuple
    - eval() : output은 logits Tensor

    GoogLeNet 헤드는 raw logits를 출력하므로 (log_softmax를 내부에 포함한)
    cross_entropy를 사용한다. Caffe loss_weight(1.0/0.3/0.3)와 논문 설정에 대응.
    """
    if torch.is_tensor(output):  # eval 모드: 단일 텐서
        return F.cross_entropy(output, target)

    # train 모드: 3개 분류기 손실 결합
    main = F.cross_entropy(output.logits, target)
    aux2 = F.cross_entropy(output.aux_logits2, target)
    aux1 = F.cross_entropy(output.aux_logits1, target)
    return main + aux_weight * (aux1 + aux2)
