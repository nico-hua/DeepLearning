import paddle
import paddle.nn.functional as F

# 该类定义了一个卷积层加批归一化层的组合。初始化函数设置卷积层和批归一化层，forward 方法中定义了前向传播过程，应用卷积、批归一化和激活函数（leaky ReLU）
class ConvBNLayer(paddle.nn.Layer):
    def __init__(self, ch_in, ch_out, 
                 kernel_size=3, stride=1, groups=1,
                 padding=0, act="leaky"):
        super(ConvBNLayer, self).__init__()
    
        self.conv = paddle.nn.Conv2D(
            in_channels=ch_in,
            out_channels=ch_out,
            kernel_size=kernel_size,
            stride=stride,
            padding=padding,
            groups=groups,
            weight_attr=paddle.ParamAttr(
                initializer=paddle.nn.initializer.Normal(0., 0.02)),
            bias_attr=False)
    
        self.batch_norm = paddle.nn.BatchNorm2D(
            num_features=ch_out,
            weight_attr=paddle.ParamAttr(
                initializer=paddle.nn.initializer.Normal(0., 0.02),
                regularizer=paddle.regularizer.L2Decay(0.)),
            bias_attr=paddle.ParamAttr(
                initializer=paddle.nn.initializer.Constant(0.0),
                regularizer=paddle.regularizer.L2Decay(0.)))
        self.act = act

        
    def forward(self, inputs):
        out = self.conv(inputs)
        out = self.batch_norm(out)
        if self.act == 'leaky':
            out = F.leaky_relu(x=out, negative_slope=0.1)
        return out
    
# 定义了一个下采样层，通过步幅为2的卷积实现图像尺寸减半。forward 方法应用该下采样卷积层。    
class DownSample(paddle.nn.Layer):
    # 下采样，图片尺寸减半，具体实现方式是使用stirde=2的卷积
    def __init__(self,
                 ch_in,
                 ch_out,
                 kernel_size=3,
                 stride=2,
                 padding=1):

        super(DownSample, self).__init__()

        self.conv_bn_layer = ConvBNLayer(
            ch_in=ch_in,
            ch_out=ch_out,
            kernel_size=kernel_size,
            stride=stride,
            padding=padding)
        self.ch_out = ch_out
    def forward(self, inputs):
        out = self.conv_bn_layer(inputs)
        return out

# 定义了一个基本残差块，包括两层卷积，前向传播时将输入和第二层卷积输出相加，实现残差连接
class BasicBlock(paddle.nn.Layer):
    """
    基本残差块的定义，输入x经过两层卷积，然后接第二层卷积的输出和输入x相加
    """
    def __init__(self, ch_in, ch_out):
        super(BasicBlock, self).__init__()

        self.conv1 = ConvBNLayer(
            ch_in=ch_in,
            ch_out=ch_out,
            kernel_size=1,
            stride=1,
            padding=0
            )
        self.conv2 = ConvBNLayer(
            ch_in=ch_out,
            ch_out=ch_out*2,
            kernel_size=3,
            stride=1,
            padding=1
            )
    def forward(self, inputs):
        conv1 = self.conv1(inputs)
        conv2 = self.conv2(conv1)
        out = paddle.add(x=inputs, y=conv2)
        return out

# 定义了多层残差块的组合，用于构建Darknet53网络的一个层级。包括一个初始残差块和多个后续残差块。     
class LayerWarp(paddle.nn.Layer):
    """
    添加多层残差块，组成Darknet53网络的一个层级
    """
    def __init__(self, ch_in, ch_out, count, is_test=True):
        super(LayerWarp,self).__init__()

        self.basicblock0 = BasicBlock(ch_in,
            ch_out)
        self.res_out_list = []
        for i in range(1, count):
            res_out = self.add_sublayer("basic_block_%d" % (i), # 使用add_sublayer添加子层
                BasicBlock(ch_out*2,
                    ch_out))
            self.res_out_list.append(res_out)

    def forward(self,inputs):
        y = self.basicblock0(inputs)
        for basic_block_i in self.res_out_list:
            y = basic_block_i(y)
        return y

# DarkNet 每组残差块的个数，来自DarkNet的网络结构图
DarkNet_cfg = {53: ([1, 2, 8, 8, 4])}

# 定义了Darknet53网络的骨干部分，用于特征提取。包括初始卷积层、下采样层和多个层级的残差块。forward 方法依次应用各层级和下采样，返回三个特征图。
class DarkNet53_conv_body(paddle.nn.Layer):
    def __init__(self):
        super(DarkNet53_conv_body, self).__init__()
        self.stages = DarkNet_cfg[53]
        self.stages = self.stages[0:5]

        # 第一层卷积
        self.conv0 = ConvBNLayer(
            ch_in=3,
            ch_out=32,
            kernel_size=3,
            stride=1,
            padding=1)

        # 下采样，使用stride=2的卷积来实现
        self.downsample0 = DownSample(
            ch_in=32,
            ch_out=32 * 2)

        # 添加各个层级的实现
        self.darknet53_conv_block_list = []
        self.downsample_list = []
        for i, stage in enumerate(self.stages):
            conv_block = self.add_sublayer(
                "stage_%d" % (i),
                LayerWarp(32*(2**(i+1)),
                32*(2**i),
                stage))
            self.darknet53_conv_block_list.append(conv_block)
        # 两个层级之间使用DownSample将尺寸减半
        for i in range(len(self.stages) - 1):
            downsample = self.add_sublayer(
                "stage_%d_downsample" % i,
                DownSample(ch_in=32*(2**(i+1)),
                    ch_out=32*(2**(i+2))))
            self.downsample_list.append(downsample)

    def forward(self,inputs):
        out = self.conv0(inputs)
        #print("conv1:",out.numpy())
        out = self.downsample0(out)
        #print("dy:",out.numpy())
        blocks = []
        for i, conv_block_i in enumerate(self.darknet53_conv_block_list): #依次将各个层级作用在输入上面
            out = conv_block_i(out)
            blocks.append(out)
            if i < len(self.stages) - 1:
                out = self.downsample_list[i](out)
        return blocks[-1:-4:-1] # 将C0, C1, C2作为返回值

# 定义了YOLOv3的检测头，包含多个卷积和批归一化层，用于提取特征。forward 方法中定义了前向传播过程。
class YoloDetectionBlock(paddle.nn.Layer):
    # define YOLOv3 detection head
    # 使用多层卷积和BN提取特征
    def __init__(self,ch_in,ch_out,is_test=True):
        super(YoloDetectionBlock, self).__init__()

        assert ch_out % 2 == 0, \
            "channel {} cannot be divided by 2".format(ch_out)

        self.conv0 = ConvBNLayer(
            ch_in=ch_in,
            ch_out=ch_out,
            kernel_size=1,
            stride=1,
            padding=0)
        self.conv1 = ConvBNLayer(
            ch_in=ch_out,
            ch_out=ch_out*2,
            kernel_size=3,
            stride=1,
            padding=1)
        self.conv2 = ConvBNLayer(
            ch_in=ch_out*2,
            ch_out=ch_out,
            kernel_size=1,
            stride=1,
            padding=0)
        self.conv3 = ConvBNLayer(
            ch_in=ch_out,
            ch_out=ch_out*2,
            kernel_size=3,
            stride=1,
            padding=1)
        self.route = ConvBNLayer(
            ch_in=ch_out*2,
            ch_out=ch_out,
            kernel_size=1,
            stride=1,
            padding=0)
        self.tip = ConvBNLayer(
            ch_in=ch_out,
            ch_out=ch_out*2,
            kernel_size=3,
            stride=1,
            padding=1)
    def forward(self, inputs):
        out = self.conv0(inputs)
        out = self.conv1(out)
        out = self.conv2(out)
        out = self.conv3(out)
        route = self.route(out)
        tip = self.tip(route)
        return route, tip


# 定义上采样模块
class Upsample(paddle.nn.Layer):
    def __init__(self, scale=2):
        super(Upsample,self).__init__()
        self.scale = scale

    def forward(self, inputs):
        # get dynamic upsample output shape
        shape_nchw = paddle.shape(inputs)
        shape_hw = paddle.slice(shape_nchw, axes=[0], starts=[2], ends=[4])
        shape_hw.stop_gradient = True
        in_shape = paddle.cast(shape_hw, dtype='int32')
        out_shape = in_shape * self.scale
        out_shape.stop_gradient = True

        # reisze by actual_shape
        out = paddle.nn.functional.interpolate(
            x=inputs, scale_factor=self.scale, mode="NEAREST")
        return out

# 定义了YOLOv3模型，包括特征提取、检测块、上采样和预测处理模块
class YOLOv3(paddle.nn.Layer):
    def __init__(self, num_classes=7):
        super(YOLOv3,self).__init__()

        self.num_classes = num_classes
        # 提取图像特征的骨干代码
        self.block = DarkNet53_conv_body()
        self.block_outputs = []
        self.yolo_blocks = []
        self.route_blocks_2 = []
        # 生成3个层级的特征图P0, P1, P2
        for i in range(3):
            # 添加从ci生成ri和ti的模块
            yolo_block = self.add_sublayer(
                "yolo_detecton_block_%d" % (i),
                YoloDetectionBlock(
                                   ch_in=512//(2**i)*2 if i==0 else 512//(2**i)*2 + 512//(2**i),
                                   ch_out = 512//(2**i)))
            self.yolo_blocks.append(yolo_block)

            num_filters = 3 * (self.num_classes + 5)

            # 添加从ti生成pi的模块，这是一个Conv2D操作，输出通道数为3 * (num_classes + 5)
            block_out = self.add_sublayer(
                "block_out_%d" % (i),
                paddle.nn.Conv2D(in_channels=512//(2**i)*2,
                       out_channels=num_filters,
                       kernel_size=1,
                       stride=1,
                       padding=0,
                       weight_attr=paddle.ParamAttr(
                           initializer=paddle.nn.initializer.Normal(0., 0.02)),
                       bias_attr=paddle.ParamAttr(
                           initializer=paddle.nn.initializer.Constant(0.0),
                           regularizer=paddle.regularizer.L2Decay(0.))))
            self.block_outputs.append(block_out)
            if i < 2:
                # 对ri进行卷积
                route = self.add_sublayer("route2_%d"%i,
                                          ConvBNLayer(ch_in=512//(2**i),
                                                      ch_out=256//(2**i),
                                                      kernel_size=1,
                                                      stride=1,
                                                      padding=0))
                self.route_blocks_2.append(route)
            # 将ri放大以便跟c_{i+1}保持同样的尺寸
            self.upsample = Upsample()
    def forward(self, inputs):
        outputs = []
        blocks = self.block(inputs)
        for i, block in enumerate(blocks):
            if i > 0:
                # 将r_{i-1}经过卷积和上采样之后得到特征图，与这一级的ci进行拼接
                block = paddle.concat([route, block], axis=1)
            # 从ci生成ti和ri
            route, tip = self.yolo_blocks[i](block)
            # 从ti生成pi
            block_out = self.block_outputs[i](tip)
            # 将pi放入列表
            outputs.append(block_out)

            if i < 2:
                # 对ri进行卷积调整通道数
                route = self.route_blocks_2[i](route)
                # 对ri进行放大，使其尺寸和c_{i+1}保持一致
                route = self.upsample(route)

        return outputs
    
    def get_pred(self,
                 outputs,
                 im_shape=None,
                 anchors = [10, 13, 16, 30, 33, 23, 30, 61, 62, 45, 59, 119, 116, 90, 156, 198, 373, 326],
                 anchor_masks = [[6, 7, 8], [3, 4, 5], [0, 1, 2]],
                 valid_thresh = 0.01):
        downsample = 32
        total_boxes = []
        total_scores = []
        for i, out in enumerate(outputs):
            anchor_mask = anchor_masks[i]
            anchors_this_level = []
            for m in anchor_mask:
                anchors_this_level.append(anchors[2 * m])
                anchors_this_level.append(anchors[2 * m + 1])

            boxes, scores = paddle.vision.ops.yolo_box(
                   x=out,
                   img_size=im_shape,
                   anchors=anchors_this_level,
                   class_num=self.num_classes,
                   conf_thresh=valid_thresh,
                   downsample_ratio=downsample,
                   name="yolo_box" + str(i))
            total_boxes.append(boxes)
            total_scores.append(
                        paddle.transpose(
                        scores, perm=[0, 2, 1]))
            downsample = downsample // 2

        yolo_boxes = paddle.concat(total_boxes, axis=1)
        yolo_scores = paddle.concat(total_scores, axis=2)
        return yolo_boxes, yolo_scores