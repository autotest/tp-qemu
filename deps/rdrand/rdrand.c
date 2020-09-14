#include <stdio.h>
#include <stdlib.h>
#include <time.h>

float randoms(float min, float max)
{
    return (float)(rand())/RAND_MAX*(max - min) + min;
}

int main()
{
    srand((unsigned int)time(0));
    printf("%f\n",randoms(-100.001, 100.001));
    return 0;
}
