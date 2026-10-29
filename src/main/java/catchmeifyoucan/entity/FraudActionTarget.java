package catchmeifyoucan.entity;

import com.fasterxml.jackson.annotation.JsonIgnore;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;

@Getter
@Entity
@Table(name = "fraud_action_targets")
public class FraudActionTarget {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Setter
    @JsonIgnore
    @ManyToOne
    @JoinColumn(name = "action_id", nullable = false)
    private FraudAction action;

    @Setter
    @ManyToOne
    @JoinColumn(name = "destination_company_id", nullable = false)
    private Company destinationCompany;

    @Setter
    @Column(nullable = false, precision = 19, scale = 2)
    private BigDecimal amount;

    public FraudActionTarget() {
    }
}
