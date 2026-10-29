package catchmeifyoucan.entity;

import com.fasterxml.jackson.annotation.JsonIgnore;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;

@Getter
@Entity
@Table(name = "fraud_positions")
public class FraudPosition {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Setter
    @JsonIgnore
    @ManyToOne
    @JoinColumn(
            name = "scenario_id",
            nullable = false
    )
    private FraudScenario scenario;
    @Setter
    @ManyToOne
    @JoinColumn(
            name = "company_id",
            nullable = false
    )
    private Company company;

    @Setter
    @Column(
            nullable = false,
            precision = 19,
            scale = 2
    )
    private BigDecimal amount;

    public FraudPosition() {
    }

}
