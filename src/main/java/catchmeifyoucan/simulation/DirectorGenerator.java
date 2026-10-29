package catchmeifyoucan.simulation;

import catchmeifyoucan.entity.Director;

import java.util.HashSet;
import java.util.Random;
import java.util.Set;

public class DirectorGenerator {

    private final Random random;

    private final Set<String> generatedNames =
            new HashSet<>();

    private static final String[] FIRST_NAMES = {
            "Raj",
            "Amit",
            "Vikram",
            "Arjun",
            "Rahul",
            "Rohan",
            "Karan",
            "Manish",
            "Sanjay",
            "Anil",
            "Neeraj",
            "Vivek",
            "Priya",
            "Anita",
            "Neha",
            "Pooja",
            "Kavita",
            "Sneha"
    };

    private static final String[] LAST_NAMES = {
            "Sharma",
            "Verma",
            "Mehta",
            "Patel",
            "Gupta",
            "Malhotra",
            "Kapoor",
            "Singh",
            "Agarwal",
            "Mishra",
            "Rao",
            "Nair",
            "Joshi",
            "Chopra",
            "Bansal"
    };

    public DirectorGenerator() {
        this(new Random());
    }

    public DirectorGenerator(long seed) {
        this.random = new Random(seed);
    }

    private DirectorGenerator(Random random) {
        this.random = random;
    }

    public Director generateDirector() {

        Director director = new Director();

        director.setName(
                generateUniqueName()
        );

        return director;
    }

    private String generateUniqueName() {

        String name;

        do {

            String firstName =
                    FIRST_NAMES[
                            random.nextInt(
                                    FIRST_NAMES.length
                            )
                            ];

            String lastName =
                    LAST_NAMES[
                            random.nextInt(
                                    LAST_NAMES.length
                            )
                            ];

            name = firstName + " " + lastName;

        } while (generatedNames.contains(name));

        generatedNames.add(name);

        return name;
    }
}