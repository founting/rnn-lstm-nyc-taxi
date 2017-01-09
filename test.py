import numpy as np
import theano
import h5py
from theano import tensor
from blocks import roles
from blocks.model import Model
from blocks.extensions import saveload
from blocks.filter import VariableFilter
from utils import get_stream, track_best, MainLoop
from config import config
from model import nn_fprop
import sys
import os
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.widgets import Button
import argparse
from sklearn import mixture
import time

locals().update(config)

def my_longitude(ndarray):
    return map(lambda x: (x - 2.1) / 4.0 - 73.925, ndarray)

def my_latitude(ndarray):
    return map(lambda x: (x - 2.0) / 4.0 + 40.775, ndarray)


def sample(x_curr, mask, fprop):

    hiddens = fprop(x_curr, mask)
    #print x_curr.shape
    #print x_curr[-1:,:,:]
    probs = hiddens.pop().astype(theano.config.floatX)
    # probs = probs[-1,-1].astype('float32')
    #print "the output shape is: "
    return probs

def gaussian_2d(x, y, x0, y0, sig):
    return 1/(2*np.pi*np.sqrt(sig)) * np.exp(-0.5*((x-x0)**2 + (y-y0)**2) / sig)

def gengmm(nc):
    g = mixture.GaussianMixture(n_components=nc)  # number of components

    return g

def plotGMM(g, n, pt):

    # plt.axis([-74.2, -73.65, 40.55, 41.0])
    delta = 0.01
    x = np.arange(-74.2, -73.65, delta)
    y = np.arange(40.55, 41.0, delta)
    X, Y = np.meshgrid(x, y)

    i=0
    Z2= g.weights_[i]*gaussian_2d(X, Y, g.means_[0, i], g.means_[1, i], g.covariances_[i])
    for i in xrange(1,n):
       Z2 = Z2+ g.weights_[i]*gaussian_2d(X, Y, g.means_[0, i], g.means_[1, i], g.covariances_[i])
    return plt.contour(X, Y, Z2)

if __name__ == '__main__':
    # Load config parameters
    locals().update(config)
    float_formatter = lambda x: "%.5f" % x
    np.set_printoptions(formatter={'float_kind':float_formatter})
    parser = argparse.ArgumentParser(
        description='Generate the learned trajectory',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    args = parser.parse_args()

    print('Loading model from {0}...'.format(save_path[network_mode]))



    x0 = tensor.matrix('features_x0', dtype = 'floatX')
    x1 = tensor.matrix('features_x1', dtype = 'floatX')

    y0 = tensor.matrix('targets_x0', dtype = 'floatX')
    y1 = tensor.matrix('targets_x1', dtype = 'floatX')

    x = tensor.stack([x0, x1], axis=2)
    y = tensor.stack([y0, y1], axis=2)

    x = x.swapaxes(0,1)
    y = y.swapaxes(0,1)

    x_mask0 = tensor.matrix('features_x0_mask', dtype = 'floatX')
    x_mask1 = tensor.matrix('features_x1_mask', dtype = 'floatX')
    y_mask0 = tensor.matrix('targets_x0_mask', dtype = 'floatX')
    y_mask1 = tensor.matrix('targets_x1_mask', dtype = 'floatX')


    x_mask = x_mask0
    x_mask = x_mask.swapaxes(0,1)

    y_mask = y_mask0
    y_mask = y_mask.swapaxes(0,1)

    cost, mu, sigma, mixing, output_hiddens, mu_linear, sigma_linear, mixing_linear, cells = nn_fprop(x, y, x_mask, y_mask, in_size[network_mode], out_size[network_mode], hidden_size[network_mode], num_layers, layer_models[network_mode][0], 'MDN', training=False)
    main_loop = MainLoop(algorithm=None, data_stream=None, model=Model(cost),
                         extensions=[saveload.Load(save_path[network_mode])])

    for extension in main_loop.extensions:
        extension.main_loop = main_loop
    main_loop._run_extensions('before_training')
    bin_model = main_loop.model
    print 'Model loaded. Building prediction function...'
    hiddens = []
    initials = []
    for i in range(num_layers):
        brick = [b for b in bin_model.get_top_bricks() if b.name == layer_models[network_mode][i] + str(i) + '-'][0]
        hiddens.extend(VariableFilter(theano_name=brick.name + '_apply_states')(bin_model.variables))
        hiddens.extend(VariableFilter(theano_name=brick.name + '_apply_cells')(cells))
        initials.extend(VariableFilter(roles=[roles.INITIAL_STATE])(brick.parameters))


    # print str(hiddens[0].shape.eval())
    # hiddens = [act[-1].flatten() for act in hiddens]
    # states_as_params = [tensor.vhiddensector(dtype=initial.dtype) for initial in initials]
    # zip(initials, states_as_params)
    fprop_mu = theano.function([x, x_mask], [mu])
    # fprop_sigma = theano.function([x], [sigma])
    # fprop_mixing = theano.function([x], [mixing])
    # states_values = [initial.get_value() for initial in initials]

    #predicted = np.array([1,1], dtype=theano.config.floatX)
    #x_curr = [[predicted]]

    #print(x[2].eval())
    file = h5py.File(hdf5_file[network_mode], 'r')

    input_x0 = file['features_x0']  # input_dataset.shape is (8928, 200, 2) features_x0
    input_x1 = file['features_x1']

    shapes = [np.asarray(piece).shape for piece in input_x0]
    # print shapes[1]
    lengths = [shape[0] for shape in shapes]
    max_sequence_length = max(lengths)

    # input_dataset = np.swapaxes(input_dataset,0,1)
    # print input_dataset.shape

    output_mu = np.empty((200, 2, components_size[network_mode]), dtype='float32')
    output_sigma = np.empty((200, components_size[network_mode]), dtype='float32')
    output_mixing = np.empty((200, components_size[network_mode]), dtype='float32')
    #sample_results = sample([x], fprop, [component_mean])
    #x_curr = [input_dataset[0,:,:]]




    for i in range(50):

        x_curr = np.zeros((max_sequence_length, 1, 2))
        x_curr_mask = np.zeros((max_sequence_length, 1))
        x_curr[:lengths[i], 0, 0] = input_x0[i]
        x_curr[:lengths[i], 0, 1] = input_x1[i]

        x_curr_mask[:lengths[i], :] = 1

        x_curr=x_curr.astype('float32')
        x_curr_mask=x_curr_mask.astype('float32')

        mu_ = sample(x_curr, x_curr_mask, fprop_mu)
        mu_ = mu_[-1]
        # print x_curr.shape
        # print x_curr_mask.shape
        # print x_curr_mask

        # sigma_ = sample(x_curr, x_mask, fprop_sigma)
        # mixing_ = sample(x_curr, fprop_mixing)
        ############  make data for the second network ########################
        # mu_ = mu_[-1]
        # print mu_.shape
        # print mu_[0]
        output_mu[i, 0, :] = mu_[0]  #my_longitude(mu_[0])
        output_mu[i, 1, :] = mu_[1]   #my_latitude(mu_[1])
        #
        # output_sigma[i, :] = sigma_[-1]
        # output_mixing[i, :] = mixing_[-1]

        # for initial, newinitial in zip(initials, newinitials):
        #    initial.set_value(newinitial[-1].flatten())
           #print newinitial[-1].flatten()

##############################################
#############  Plotting  #####################
index = 0
plt.ion()
fig, ax = plt.subplots()

plt.subplots_adjust(bottom=0.2)
# plt.axes([-5, 5, -5, 5])
original_longitude = input_x0
original_latitude = input_x1

# longitude = input_dataset[:, index, 0]
# longitude = longitude[longitude > 0.5]
# longitude = longitude[longitude < 4]
# original_longitude = my_longitude(longitude)
#
# latitude = input_dataset[:, index, 1]
# latitude = latitude[latitude > 0.5]
# latitude = latitude[latitude < 4]
# original_latitude = my_latitude(latitude)
#
#
l1, = plt.plot(original_longitude[index], original_latitude[index], 'bo')
l2, = plt.plot(output_mu[index, 0, :], output_mu[index, 1, :], 'ro')

# g = gengmm(400)
# g.means_=output_mu[index,:,:]
# g.weights_=output_mixing[index,:]
# g.covariances_ = output_sigma[index,:]
#
# delta = 0.01
# x = np.arange(-74.2, -73.65, delta)
# y = np.arange(40.55, 41.0, delta)
# X, Y = np.meshgrid(x, y)
#
# i=0
# Z2= g.weights_[i]*gaussian_2d(X, Y, g.means_[0, i], g.means_[1, i], g.covariances_[i])
#
# for i in xrange(1,400):
#     Z2 = Z2+ g.weights_[i]*gaussian_2d(X, Y, g.means_[0, i], g.means_[1, i], g.covariances_[i])

# c =  plt.contour(X, Y, Z2)
# l2 = plt.clabel(c)


# l2 = plotGMM(g, 600, 0)




plt.title("Prediction Demo")
plt.xlabel("longitude")
plt.ylabel("latitude")


class Index(object):
    index = 0

    def next(self, event):
        self.index += 1

        # longitude = input_dataset[:, self.index, 0]
        # original_longitude = my_longitude(longitude[longitude > 0.5])
        #
        # latitude = input_dataset[:, self.index, 1]
        # original_latitude = my_latitude(latitude[latitude > 0.5])
        #
        l1.set_xdata(original_longitude[self.index])
        l1.set_ydata(original_latitude[self.index])

        # g.means_=output_mu[self.index,:,:]
        # g.covariances_=output_sigma[self.index,:]
        # g.weights_=output_mixing[self.index,:]
        # # g = gengmm(600, 2, output_mu[self.index], output_sigma[self.index], output_mixing[self.index])
        # i=0
        # Z2= g.weights_[i]*gaussian_2d(X, Y, g.means_[0, i], g.means_[1, i], g.covariances_[i])
        # for i in xrange(1,600):
        #     Z2 = Z2+ g.weights_[i]*gaussian_2d(X, Y, g.means_[0, i], g.means_[1, i], g.covariances_[i])
        # ax.contour(X, Y, Z2)
        # time.sleep(1)
        l2.set_xdata(output_mu[self.index, 0, :])
        l2.set_ydata(output_mu[self.index, 1, :])
        # plt.axes([-74.2, -73.65, 40.55, 41.0])
        plt.draw()
        # ax.collections = []


callback = Index()
axnext = plt.axes([0.81, 0.05, 0.1, 0.075])
bnext = Button(axnext, 'Next')
bnext.on_clicked(callback.next)
plt.ioff()
plt.show()
