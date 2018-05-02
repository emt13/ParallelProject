import numpy as np
from mpi4py import MPI
from batch_helper import scatter_data, all_reduce_data
from layers import l2_loss, fully_connected_layer, softmax_loss
from sklearn import preprocessing
    
import sys

class NeuralNetwork:

        def __init__(self, nodes_model = 1, nodes_batch = 1):
                """
                Initialize the NeuralNetwork

                :param nodes_model: int, number of nodes to use for model parallelism 
                :param nodes_batch: int, number of nodes to use for batch parallelism
                """
                self.layers = []
                self.loss = None
                self.nodes_model = nodes_model
                self.nodes_batch = nodes_batch
                pass

        def add_layer(self, layer_type, size_input=0, size_output=0):
                """
                Add a layer to the NeuralNetwork. 
                """
                self.layers.append((layer_type, size_input, size_output))
        
        def add_loss(self, loss_function):
            self.loss = loss_function

        def train_model_parallelism(self, x, y, epochs, mini_batch_size, eta, test_data=None):
                """
                TODO: Training procedure for model parallelism
                """
                x_shape = x.shape
                y_shape = y.shape

                mini_batch_shapes = [len(x[k:k + mini_batch_size]) for k in range(0, len(x), mini_batch_size)]
                #print(mini_batch_shapes, mini_batch_size)

                # mpi init
                comm = MPI.COMM_WORLD
                rank = comm.Get_rank()
                size = comm.Get_size()
                
                #TODO
                # Create the layers themselves
                layers, loss = self._init_layers(rank, size)
               
                start = MPI.Wtime()
                epochTimes = []
 
                for e in range(epochs):
                    print("starting epoch:",e)
                    eStart = MPI.Wtime()
                    training_data = list(zip(list(x), list(y)))
                    n = len(training_data)
                    np.random.shuffle(training_data)
                    mini_batches =[training_data[k:k+mini_batch_size] for k in range(0, n, mini_batch_size)]
                    
                    for i in range(len(mini_batch_shapes)):
                        # Naming convention
                        # variable_all means that variable is common to all processes
                        # all_variable referes to a lsit of variables from each layer
                        x_all = np.array([j[0] for j in mini_batches[i]])
                        y_all = np.array([j[1] for j in mini_batches[i]])
                        all_zs_reduced = [x_all]
                        
                        for layer in layers:
                            z_rank = layer.forward(x_all)
                            z_reduced = all_reduce_data(z_rank, comm, rank, size)
                            all_zs_reduced.append(z_reduced)
                            x_all = z_reduced
                        
                        loss_value, dy = loss.loss(all_zs_reduced[-1], y_all)
                        
                        
                        for layer in reversed(layers):
                            #TODO
                            dx_rank, dw_rank, db_rank = layer.backward(dy)
                            dx_reduced = all_reduce_data(dx_rank, comm, rank, size)
                            dy = dx_reduced
                            
                            #TODO 
                            layer.apply_gradient(dw_rank, db_rank, eta, mini_batch_shapes[i])
                            
                    #if test_data:
                    #    print ("Epoch {0}/{1} complete - loss: {2}".format(e+1, epochs, self.evaluate(test_data, layers, loss)))
                    #else:
                    #    print ("Epoch {0}/{1} complete".format(e+1, epochs))
                    eEnd = MPI.Wtime()
                    epochTimes.append(eEnd - eStart)
        
                if rank == 0:
                    end = MPI.Wtime()
                    print("Finished model in", end - start)
                    for i in range(len(epochTimes)):
                        print("  ", i, "  ", epochTimes[i])             
                    print()
                                
                            

        def train_batch_parallelism(self, x, y, epochs, mini_batch_size, eta, test_data=None):
                """
                Training procedure for batch parallelism
                """
                x_shape = x.shape
                y_shape = y.shape

                mini_batch_shapes = [len(x[k:k + mini_batch_size]) for k in range(0, len(x), mini_batch_size)]
                

                # mpi init
                comm = MPI.COMM_WORLD
                rank = comm.Get_rank()
                size = comm.Get_size()
 
                if rank != 0:
                    del x
                    del y
               
                # Create the layers themselves
                layers, loss = self._init_layers()
               
                start = MPI.Wtime()
                epochTimes = []   

                time_scatter_total = 0
                time_all_reduce_total = 0
                
                #print(x)
                #print(y)
                #print()
       
                # for 1 ... epoch:
                for e in range(epochs):
                    print("starting epoch:",e)
                    eStart = MPI.Wtime()
                    if(rank==0):
                        #print(e, eStart)
                        training_data = list(zip(list(x), list(y)))
                        n = len(training_data)
                        np.random.shuffle(training_data)
                        mini_batches =[training_data[k:k+mini_batch_size] for k in range(0, n, mini_batch_size)]
                  
                    #for mini_batch in mini_batches:
                    for i in range(len(mini_batch_shapes)):
                        
                        all_x = None
                        all_y = None
                        if rank == 0:
                            all_x = np.array([j[0] for j in mini_batches[i]])
                            all_y = np.array([j[1] for j in mini_batches[i]])
                        
                        time_scatter_total_start = MPI.Wtime()
                        x_rank = scatter_data(all_x, (mini_batch_shapes[i], x_shape[1]) , comm, rank, size)
                        #print('x',x_rank)
                
                        y_rank = scatter_data(all_y, (mini_batch_shapes[i], y_shape[1]) , comm, rank, size)
                        #print('y', y_rank)
                        time_scatter_total += MPI.Wtime() - time_scatter_total_start
                        #print("rank:", rank, "xshape", x_rank.shape, "yshape", y_rank.shape)

                        # The following if statement solves the problem when there is one single data to scatter on 2 processes. The second process will receive an empty data...
                        if x_rank.size != 0:                                              
                            all_zs = [x_rank]
                            for layer in layers:
                                z = layer.forward(x_rank)
                                #print(" -- ", z.shape, z)
                                all_zs.append(z)
                                x_rank = z
                            
                            loss_value, dy = loss.loss(all_zs[-1], y_rank)
                            #print(all_zs[-1])
                            
                            #print(all_zs[-1], dy.shape) 
                            dws, dbs = [], []
                            for layer in reversed(layers):
                                dx, dw, db = layer.backward(dy)
                                
                                dy = dx
                                dws.append(dw)
                                dbs.append(db)
                            
                        else:    
                            dws, dbs = [], []
                            for layer in reversed(layers):
                                dw = np.zeros(layer.w.shape)
                                db = np.zeros(layer.b.shape)
                                dws.append(dw)
                                dbs.append(db)
                        
                        time_all_reduce_time_start = MPI.Wtime() 
                        reduced_dws = all_reduce_data(dws, comm, rank, size)

                        reduced_dbs = all_reduce_data(dbs, comm, rank, size)
                        time_all_reduce_total += MPI.Wtime() - time_all_reduce_time_start
                        
                        L = len(layers)

                        for j in range(L):
                            layer = layers[L-1-j]
                            layer.apply_gradient(reduced_dws[j],reduced_dbs[j], eta, mini_batch_shapes[i])
                    
                    """
                    if rank == 0:
                        print("weights first layer", layers[0].w)
                    """
                    if rank == 0:
                        eEnd = MPI.Wtime()
                        #print(" ", eEnd)
                        epochTimes.append(eEnd - eStart)
                        '''
                        count = 1
                        print("number of layers:", len(layers))
                        for l in layers:
                            print(" -- ", count, " --")
                            print(rank, l.w)
                            print("++")
                            print()
                            count += 1
                        '''
                        #if test_data:
                        #   print ("Epoch {0}/{1} complete - loss: {2}".format(e+1, epochs, self.evaluate(test_data, layers, loss)))
                        #else:
                        #   print ("Epoch {0}/{1} complete".format(e+1, epochs))
                if rank == 0:
                    end = MPI.Wtime()
                    print("Total time was:", end - start)
                    print("Scatter time:", time_scatter_total)
                    print("All reduce time:", time_all_reduce_total)
                    for i in range(len(epochTimes)):
                        print("  (" + str(i) + ")", epochTimes[i]) 
                    print()
                
        def evaluate(self, test_data, layers, loss):
            test_results = [(self.feedforward(np.array([x_test]), layers), y_test)
                            for (x_test, y_test) in test_data]
            n_test = len(test_data)
            return (1.0/(1.0*n_test) * sum(loss.loss(y_predicted, y_truth)[0] for (y_predicted, y_truth) in test_results))
        
        def feedforward(self, a, layers):
            """Return the output of the network if ``a`` is input."""
            for layer in layers:
                a = layer.forward(a)
            return a


        def test(self, x):
                """
                TODO: Test procedure
                """
                pass

        def train(self, x, y):
                """
                TODO: Combined training procedure for model and batch parallelism
                """
                pass

        def train_serial(self, x, y):
            layers, loss = self.init_layers() 
            
                

        def _init_layers(self, rank=1, size=1, seed=0):
            layers = []
            loss = None 
            seed = 0
            for layer in self.layers:
                if layer[0] == "fc":
                    # Important note here: every layer is initialized on each process.
                    # The initialization is random so: either we broadcast the weights and biases
                    # Or we add a seed in layer. For now, we chose the latter.
                    mask = _create_mask(rank, size, layer[1], layer[2])
                    layers.append(fully_connected_layer(layer[1], layer[2], seed, mask))
                else:
                    print(layer[0], "is not valid")
                    return []
                seed += 1
            if self.loss == "l2":
                loss = l2_loss()
            elif self.loss == "softmax":
                loss = softmax_loss()
            else : 
                print("invalid loss layer")
                return []
            return layers, loss


def _load_data(f, delimiter=","):
    data = []
    count = 0
    for l in f:
        split = l.split(delimiter)
        sub = []
        for s in split:
            try:
                sub.append(float(s))
            except Exception as e:
                sub.append("Error")
                
        data.append(sub)
        count += 1
    f.close()

    return np.array(data).reshape((len(data), len(data[0])))


# nodes_model ???
# rank: curr_rank, size: number of ranks
# assumes size is divisible by size_output
def _create_mask(rank, size, size_input, size_output, nodes_model=1):
    if size == 1:
        mask = None
    else:
        mask_base = np.zeros(size_output)
        local_length = size_output / size
        start_ind = int(local_length * rank)
        end_ind = int(local_length * (rank + 1))
        # print("length", local_length, "start", start_ind, "end", end_ind)
        mask_base[start_ind:end_ind] = 1
        mask = np.repeat(np.array([mask_base]), size_input, axis=0)

    # print(mask_base)
    # print(mask)
    return mask

def _fetchData(dataset):
    x, y = None, None
    if dataset.lower() == "large":
        data = _load_data(open("Data/ethylene_methane.csv", "r"), delimiter=",")
        x = data[:,3:]
        y = data[:,1:3]
    elif dataset.lower() == "medium":
        data = _load_data(open("Data/airfoil_self_noise.dat", "r"), delimiter="\t")
        x = data[:,1:5]
        y = data[:,5].reshape(len(x), 1)
    elif dataset.lower() == "toy":
        x = np.random.randn(100, 2)
        y = np.transpose([np.sin(x[:,0])])
    elif dataset.lower() == "basic":
        x = np.array([[1,2,3],[3,4,5],[5,6,7]])
        y = np.array([[6],[12],[18]])  
 
    #scaler = preprocessing.StandardScaler()
    #scaler.fit(x)
    #x = scaler.transform(x)
 
    x_train = x[:int(len(x)*.8)]
    y_train = y[:int(len(y)*.8)]
    
    x_test = x[int(len(x)*.8):]
    y_test = y[int(len(y)*.8):]
   
    return x_train, y_train, x_test, y_test
   

# has all of the testing code
def main():
    if len(sys.argv) < 6:
        print("Input error, needs to be: python neuralnet.py <model, batch, both> <dataset (large, huge)> <num epochs> <mini batch size> <eta> <comma separated, no spaces number of neurons in each layer>")
        return

    batch_nodes = int(sys.argv[1])
    model_nodes = int(sys.argv[2])
    typeParallel = sys.argv[3]
    dataset = sys.argv[4]
    epochs = int(sys.argv[5])
    mini_batch_size = int(sys.argv[6])
    eta = float(sys.argv[7])
    neurons = [int(x) for x in sys.argv[8].split(",")]
    
    rank = MPI.COMM_WORLD.Get_rank()

    if rank == 0:
        print("configured to run:")
        print(" batch nodes", batch_nodes)
        print(" model nodes", model_nodes)
        print(" type:", typeParallel)
        print(" dataset:", dataset)
        print(" epochs:", epochs)
        print(" mini batch size:", mini_batch_size)
        print(" eta:", eta)
        print(" neurons:", neurons)
        
        print("Starting test...")
        print(" Fetching data...")
    x_train, y_train, x_test, y_test = _fetchData(dataset)
    test_data = list(zip(list(x_test), list(y_test)))

    if rank == 0:
        print(" succesfully fetched the data.")
        print("  x_train shape:", x_train.shape)
        print("  y_train shape:", y_train.shape)
        print("  x_test shape:", x_test.shape)
        print("  y_test shape:", y_test.shape)

        print(" Creating the neural network...")
    nn = NeuralNetwork(nodes_model=model_nodes, nodes_batch=batch_nodes)
    
    prevSize = x_train.shape[1]
    for s in neurons:
        nn.add_layer("fc", prevSize, s // model_nodes)
        if rank == 0:
            print("  added layer |", prevSize,"->", s // model_nodes)
        prevSize = s // model_nodes
    nn.add_layer("fc", prevSize, y_train.shape[1])   
    
    if rank == 0: 
        print("  added output layer |", prevSize,"->",y_train.shape[1])
    nn.add_loss("l2")
    if rank == 0:
        print("  added loss layer")
        print(" Finished creating network.")
        
        print(" Beginning training the network...")
    if typeParallel.lower() == "model":   
        nn.train_model_parallelism(x_train, y_train, epochs, mini_batch_size,eta, test_data = test_data)
    elif typeParallel.lower() == "batch":
        nn.train_batch_parallelism(x_train, y_train, epochs, mini_batch_size, eta, test_data=test_data)
    elif typeParallel.lower() == "both":
        pass
    else:
        print("ERROR: need to use either model, batch, or both")

    if rank == 0:
        print("Finished test")

if __name__=="__main__":
   main() 





