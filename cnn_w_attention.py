from keras.models import Model
from keras.layers import Dense, Conv2D, MaxPooling1D, Input, Embedding, Conv1D, AveragePooling1D, Flatten, Dot, Multiply, Activation, Dropout
from keras.layers import Concatenate, Add, Lambda
from keras.optimizers import adam
from keras.utils.np_utils import to_categorical
from keras.losses import categorical_crossentropy
from keras import backend as K
from keras.callbacks import EarlyStopping
import pickle
import numpy as np
INPUT_SHAPE = (40,)
N_AUTHORS = 3
dicts = pickle.load(open('./dictionaries.p', 'rb'))
training_set = pickle.load(open('./train_dataset.p', 'rb'))


def attention_layer(inputs, filters):
    #Compute Feature Maps
    M = Conv1D(filters=filters, kernel_size=1, padding='same', activation='softmax')
    M_out = M(inputs)
    mp = Multiply()
    Z = mp([inputs, M_out])
    #Dimension Reduction
    reduce_dims = AveragePooling1D(pool_size=2, strides=2, padding='same')
    reduce_dims_out = reduce_dims(Z)
    #Attention Class Prediction
    fc = Dense(N_AUTHORS, activation='softmax')
    _class = fc(reduce_dims_out)
    #Calculate Confidence
    confidence_layer = Dense(N_AUTHORS, activation='sigmoid')
    c_layer_out = confidence_layer(reduce_dims_out)
    confidence = Lambda(lambda x: K.sum(x, axis=0))([c_layer_out])
    return (M_out, Z, _class, confidence)

def frobinius_regulzarization(maps):
    norms = []
    for x in range(1, len(maps)):
        norms.append(K.sqrt(K.sum((maps[x]-maps[x-1])**2)))
    return K.sum(norms)

def losses(maps):
    def combined_loss(y_true, y_pred):
        loss1 = categorical_crossentropy(y_true, y_pred)
        loss2 = frobinius_regulzarization(maps)
        return loss1 + 0.1*loss2
    return combined_loss

def calculate_attention_weight(confidences, att_preds):
    softmaxes = []
    for x,y in zip(confidences, att_preds):
        softmaxes.append(Lambda(lambda x: K.softmax(x[0]*x[1]))([x, y]))
    return Add()(softmaxes)

def conv_attn_blocks(inputs, n=1):
    _inputs = inputs
    attn_maps = []
    attn_confidences = []
    attn_preds = []
    for _ in range(0, n):
        conv1 = Conv1D(filters=128, kernel_size=3, padding='same', activation='relu')
        conv2 = Conv1D(filters=128, kernel_size=5, padding='same', activation='relu')
        mp1 = MaxPooling1D(pool_size=(32,), padding='same')
        mp2 = MaxPooling1D(pool_size=(2,), padding='same')
        #conv block 1
        conv1_out = conv1(_inputs)
        mp1_out = mp1(conv1_out)
        #attn block 1
        attention1 = attention_layer(mp1_out, 128)
        attn_maps.append(attention1[0])
        attn_confidences.append(attention1[-1])
        attn_preds.append(attention1[-2])
        #conv block 2
        conv2_out = conv2(mp1_out)
        mp2_outs = mp2(conv2_out)
        #attn block 2
        attention2 = attention_layer(mp2_outs, 128)
        attn_maps.append(attention2[0])
        attn_confidences.append(attention2[-1])
        attn_preds.append(attention2[-2])
        #predictions
        dropout = Dropout(0.8)
        _inputs = dropout(mp2_outs)
    return (_inputs, attn_maps, attn_confidences, attn_preds)

def attn_build_cnn_return_preds(inputs, n_layers):
    # Embed the words
    embed = Embedding(len(dicts['r_dict']), 40, input_length=40)
    embedded_inputs = embed(inputs)
    conv_outs, attn_maps, attn_confidences, attn_preds = conv_attn_blocks(embedded_inputs, n_layers)
    fc_final = Dense(N_AUTHORS, activation='softmax')
    fc_final_out = fc_final(conv_outs)
    #network without attention confidence score
    confidence_layer = Dense(N_AUTHORS, activation='sigmoid')
    c_out = Lambda(lambda x: K.sum(x, axis=0))(confidence_layer(conv_outs))
    #get how much each attention head should contribute
    attn_attributions = calculate_attention_weight(attn_confidences, attn_preds)
    #apply the confidence to the predictions
    gated_out = Multiply()([c_out, fc_final_out])
    #add the contributions from the attention heads
    attention_weighted_out = Add()([gated_out, attn_attributions])
    return (attention_weighted_out, attn_maps)
