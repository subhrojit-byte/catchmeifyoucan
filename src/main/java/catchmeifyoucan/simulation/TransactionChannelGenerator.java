package catchmeifyoucan.simulation;

import java.util.Random;

/** Shared channel distribution independent of hidden company labels. */
public final class TransactionChannelGenerator {

    private TransactionChannelGenerator() {
    }

    public static String generateChannel(Random random) {
        double value = random.nextDouble();
        if (value < 0.45) return "BANK_TRANSFER";
        if (value < 0.70) return "UPI";
        if (value < 0.85) return "ONLINE_PAYMENT";
        if (value < 0.95) return "CHEQUE";
        return "CASH";
    }
}
